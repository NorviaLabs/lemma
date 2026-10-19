"""Durable lesson request lifecycle without live providers or downloads."""
import json
import http.client
import os
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from lemma import generate, ingest, server, store


def _raise(e):
    raise e
from lemma.llm import ProviderError
import fakejev  # noqa: E402,F401  Jev is essential, so every search and build asks this stand-in
from test_lemma import SOURCE, FakeProvider
from test_multisource import MultiSourceProvider


class RequestTests(unittest.TestCase):
    def setUp(self):
        # A build settles before its thread's last progress write, so cleanup can race that write.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {'LEMMA_HOME': self.tmp.name})
        self.env.start()
        self.hosted = patch.object(server, 'HOSTED', False)
        self.hosted.start()
        self.provider = patch.object(server, '_provider', return_value=MultiSourceProvider())
        self.provider.start()

    def tearDown(self):
        self.provider.stop()
        self.hosted.stop()
        self.env.stop()
        self.tmp.cleanup()

    def settled(self, rid):
        for _ in range(1000):  # up to 10 s: a build settles in the background, slower when the whole suite runs
            record = server.api_request(rid)
            if record['status'] != 'running':
                return record
            time.sleep(.01)
        self.fail('request did not settle')

    def create(self):
        return server.api_request_create({'sources': [{'url': 'https://example.org/paper', 'title': 'Paper'}], 'topic': 'Regression'})['id']

    def test_complete_review_build_persist_and_delete(self):
        with patch.object(server, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)):
            rid = self.create()
            outline = self.settled(rid)
        self.assertEqual(outline['status'], 'awaiting_outline', outline.get('error'))
        self.assertNotIn('paper', outline)
        self.assertNotIn('request', outline)
        self.assertEqual(server.api_requests({})[0]['id'], rid)
        server.REQUEST.body = {'outline': outline['outline']}
        server.api_request_outline(rid)
        done = self.settled(rid)
        self.assertEqual(done['status'], 'done', done.get('error'))
        lesson, source = store.load_lesson(rid)
        self.assertEqual(lesson['id'], rid)
        self.assertIn('lemma_sources', source)
        self.assertEqual(store.request_path(rid).stat().st_mode & 0o777, 0o600)
        server.api_lesson_delete(rid)
        self.assertFalse(store.request_path(rid).exists())

    def test_without_jev_no_build_is_started_or_saved(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}), patch.object(server, '_first_readable') as read:
            with self.assertRaises(server.ApiError) as raised:
                self.create()
        self.assertEqual(raised.exception.status, 503)
        self.assertIn('TYPESAFE_API_KEY', raised.exception.message)
        read.assert_not_called()
        self.assertEqual(server.api_requests({}), [])

    def test_a_built_lesson_carries_its_category(self):
        with patch.object(server, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)):
            rid = self.create()
            outline = self.settled(rid)
        server.REQUEST.body = {'outline': outline['outline']}
        server.api_request_outline(rid)
        done = self.settled(rid)
        self.assertEqual(done['status'], 'done', done.get('error'))
        self.assertEqual(store.load_lesson(rid)[0]['category']['model'], 'jev-test')

    def test_sources_are_read_at_the_same_time_and_keep_their_order(self):
        def slow(urls):
            time.sleep(.4 if 'a.example' in urls[0] else .1)  # the first source finishes last
            return SimpleNamespace(title=urls[0], url=urls[0], text=SOURCE)
        sources = [{'url': f'https://{c}.example', 'title': c} for c in 'abc']
        start = time.monotonic()
        with patch.object(server, '_first_readable', side_effect=slow):
            record = self.settled(server.api_request_create({'sources': sources})['id'])
        self.assertLess(time.monotonic() - start, .9)  # one after another would take at least 0.6s of reading alone
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        bundle = json.loads(store.load_request(record['id'])['paper']['text'])['lemma_sources']
        self.assertEqual([(s['id'], s['url']) for s in bundle], [('s1', 'https://a.example'), ('s2', 'https://b.example'), ('s3', 'https://c.example')])

    def test_search_runs_in_the_background_and_reports_progress(self):
        from lemma import search
        search._cache.clear()
        release = threading.Event()

        def slow(query, on_progress=None):
            on_progress({'services': {'Wikipedia': 'done', 'OpenAlex': 'searching'}, 'found': {'Wikipedia': 1},
                         'to_check': 0, 'checked': 0, 'readable': 0})
            release.wait(5)
            return {'query': query, 'kind': 'concept', 'results': [], 'unavailable': [], 'checked_at': time.time()}

        with patch.object(search, '_search', side_effect=slow):
            started = server.api_search({'query': '  free   will '})
            self.assertFalse(started['done'])
            self.assertEqual(started['query'], 'free will')
            for _ in range(100):
                status = server.api_search_status(started['id'])
                if status['progress']:
                    break
                time.sleep(.01)
            self.assertEqual(status['progress']['services']['OpenAlex'], 'searching')  # seen while it runs
            release.set()
            for _ in range(1000):  # up to 10 s: a build settles in the background, slower when the whole suite runs
                status = server.api_search_status(started['id'])
                if status['done']:
                    break
                time.sleep(.01)
            self.assertEqual((status['done'], status['error'], status['result']['query']), (True, '', 'free will'))
            again = server.api_search({'query': 'Free will'})  # a recent search is answered at once
            self.assertEqual((again['done'], again['result']['query']), (True, 'free will'))
        with self.assertRaises(server.ApiError):
            server.api_search({'query': '   '})
        with self.assertRaises(server.ApiError):
            server.api_search_status('0123456789ab')

    def test_partial_failure_restart_and_retry(self):
        server._provider.return_value.source_id = 's2'
        with patch.object(server, '_first_readable', side_effect=lambda urls: _raise(ingest.IngestError('blocked')) if 'a.example' in urls[0] else SimpleNamespace(title='Galton', url='', text=SOURCE)):
            rid = server.api_request_create({'sources': [{'url': 'https://a.example', 'title': 'Blocked'}, {'url': 'https://b.example', 'title': 'Readable'}]})['id']
            record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        self.assertIn('Blocked', record['warnings'][0])
        disk = store.load_request(rid)
        disk['status'] = 'running'
        store.save_request(disk)
        generate.JOBS.pop(rid)
        self.assertEqual(server.api_request(rid)['status'], 'interrupted')
        server.api_request_retry(rid)
        self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
        server.api_request_cancel(rid)
        self.assertEqual(server.api_request(rid)['status'], 'cancelled')
        server.api_request_delete(rid)
        self.assertFalse(store.request_path(rid).exists())

    def test_all_failed_validation_and_isolation(self):
        with patch.object(server, '_first_readable', side_effect=ingest.IngestError('unreadable')):
            rid = self.create()
            self.assertEqual(self.settled(rid)['status'], 'error')
        self.assertNotIn('key', json.dumps(store.load_request(rid)).lower())
        with self.assertRaises(server.ApiError):
            server.api_request_create({'sources': []})
        with self.assertRaises(server.ApiError):
            server.api_request_create({'sources': [{'url': 'file:///secret'}]})
        with patch.object(server, 'HOSTED', True):
            server.REQUEST.user = {'id': 'different'}
            with self.assertRaises(server.ApiError):
                server.api_request(rid)
            self.assertEqual(server.api_requests({}), [])

    def test_http_outline_body_and_credential_free_storage(self):
        httpd = server.make_server(0, exact=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        def request(method, path, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', httpd.server_address[1])
            connection.request(method, path, json.dumps(body) if body else None,
                               {'Content-Type': 'application/json', 'X-Lemma-Key': 'test-secret-never-store'})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200, data)
            return data
        try:
            with patch.object(server, '_first_readable', return_value=SimpleNamespace(title='Galton', url='', text=SOURCE)):
                rid = request('POST', '/api/requests', {'sources': [{'url': 'https://example.org'}]})['id']
                outline = self.settled(rid)['outline']
            request('POST', f'/api/requests/{rid}/outline', {'outline': outline})
            self.assertEqual(self.settled(rid)['status'], 'done')
            self.assertNotIn('test-secret-never-store', store.request_path(rid).read_text())
            self.assertEqual(request('GET', f'/api/requests/{rid}')['status'], 'done')
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_provider_error_cannot_persist_echoed_key(self):
        server.REQUEST.headers = {'X-Lemma-Key': 'secret-test-key'}
        try:
            with patch.object(server, '_first_readable', return_value=SimpleNamespace(title='Galton', url='', text=SOURCE)), patch.object(generate, 'make_outline', side_effect=ProviderError('Invalid key secret-test-key')):
                rid = self.create()
                self.assertEqual(self.settled(rid)['status'], 'error')
            self.assertNotIn('secret-test-key', store.request_path(rid).read_text())
            self.assertIn('[redacted]', server.api_request(rid)['error'])
        finally:
            server.REQUEST.headers = {}

    def test_long_source_text_is_not_rejected_or_truncated(self):
        text = 'Full source content.\n' * 80_000
        paper = ingest.from_bytes(text.encode(), filename='long.txt')
        self.assertGreater(len(paper.text), 1_500_000)
        self.assertEqual(paper.text, text.strip())

        with patch.object(server, '_first_readable', return_value=paper), patch.object(generate, 'make_outline', return_value={}) as outline:
            rid = self.create()
            self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
            supplied = json.loads(outline.call_args.args[2])['lemma_sources'][0]['text']
            self.assertEqual(supplied, paper.text)

        with patch.object(server, '_paper', return_value={'text': paper.text, 'title': 'Long upload', 'url': '', 'owner': None}), patch.object(generate, 'make_outline', return_value={}) as outline:
            rid = server.api_request_create({'paper_id': 'upload'})['id']
            self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
            self.assertEqual(outline.call_args.args[2], paper.text)
