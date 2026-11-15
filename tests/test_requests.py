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
from lemma import lesson as L


def _raise(e):
    raise e
from lemma.llm import ProviderError
import fakejev  # noqa: E402,F401  Jev is essential, so every search and build asks this stand-in
from support import SOURCE, TESTER, call, reset_server, session_cookie, sign_in
from test_lemma import FakeProvider
from test_multisource import MultiSourceProvider


class RequestTests(unittest.TestCase):
    def setUp(self):
        # A build settles before its thread's last progress write, so cleanup can race that write.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {'LEMMA_HOME': self.tmp.name})
        self.env.start()
        sign_in()
        self.provider = patch.object(server.core, '_provider', return_value=MultiSourceProvider())
        self.provider.start()

    def tearDown(self):
        self.provider.stop()
        reset_server()
        self.env.stop()
        self.tmp.cleanup()

    def settled(self, rid):
        for _ in range(1000):  # up to 10 s: a build settles in the background, slower when the whole suite runs
            record = call(server.api_request, rid)
            if record['status'] != 'running':
                return record
            time.sleep(.01)
        self.fail('request did not settle')

    def create(self):
        return call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper', 'title': 'Paper'}], 'topic': 'Regression'})['id']

    def test_complete_review_build_persist_and_delete(self):
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)):
            rid = self.create()
            outline = self.settled(rid)
        self.assertEqual(outline['status'], 'awaiting_outline', outline.get('error'))
        self.assertNotIn('paper', outline)
        self.assertNotIn('request', outline)
        self.assertEqual(call(server.api_requests)[0]['id'], rid)
        call(server.api_request_outline, rid, body={'outline': outline['outline']})
        done = self.settled(rid)
        self.assertEqual(done['status'], 'done', done.get('error'))
        lesson, source = store.load_lesson(rid, TESTER)
        self.assertEqual(lesson['id'], rid)
        self.assertIn('lemma_sources', source)
        self.assertEqual(store.request_path(rid, TESTER).stat().st_mode & 0o777, 0o600)
        call(server.api_lesson_delete, rid)
        self.assertFalse(store.request_path(rid, TESTER).exists())

    def test_the_level_reaches_the_prompts_and_is_remembered(self):
        provider = server.core._provider()
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)):
            rid = call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper', 'title': 'Paper'}], 'level': 'advanced'})['id']
            outline = self.settled(rid)
        self.assertEqual(outline['status'], 'awaiting_outline', outline.get('error'))
        self.assertIn("The learner's level: Advanced: has studied or works in the field", provider.tasks['outline'])
        self.assertEqual(call(server.api_status)['level'], 'advanced')  # offered first next time
        call(server.api_request_outline, rid, body={'outline': outline['outline']})
        self.assertEqual(self.settled(rid)['status'], 'done')
        lesson, _ = store.load_lesson(rid, TESTER)
        self.assertEqual(lesson['level'], 'advanced')
        concept = next(t for k, t in provider.tasks.items() if k != 'outline')
        self.assertIn("The learner's level: Advanced", concept)

    def test_the_search_a_lesson_was_asked_for_from_reaches_the_outline(self):
        search = {'query': '  Why does   stress make you sick? ', 'field': ['medicine', 'psychology', 'astrology'],
                  'subjects': [{'title': 'Cortisol', 'need': 3.3, 'relation': 'part'}, {'title': 'Gossip', 'need': 1.2, 'relation': 'unrelated'},
                               {'title': 'x' * 300, 'need': 4, 'relation': 'prerequisite'}, {'title': 'Odd', 'need': 9, 'relation': 'part'}],
                  'not_covered': ['Allostatic load', 7]}
        seen = {}

        def outline(job, provider, text, level, search=None):
            seen['search'] = search
            raise generate.GenerationError('stop here')
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)), \
                patch.object(generate, 'make_outline', side_effect=outline):
            self.settled(call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper', 'title': 'Paper'}], 'search': search})['id'])
        self.assertEqual(seen['search'], {'query': 'Why does stress make you sick?', 'field': ['medicine', 'psychology'],
                                          'subjects': [{'title': 'Cortisol', 'need': 3.3, 'relation': 'part'},
                                                       {'title': 'x' * 200, 'need': 4.0, 'relation': 'prerequisite'}],
                                          'not_covered': ['Allostatic load']})
        for bad in ('stress', {'query': ''}, {'field': ['medicine']}):
            with self.assertRaises(server.ApiError) as e:
                call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper'}], 'search': bad})
            self.assertEqual((e.exception.status, e.exception.message), (400, 'Invalid search.'))

    def awaiting_with_suggestions(self):
        """A request at outline review whose outline suggests two sources to add (an assumed subject's article)."""
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)):
            rid = self.create()
            self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
        record = store.load_request(rid, TESTER)
        record['outline']['subjects'] = [{'title': 'Correlation', 'url': 'https://en.wikipedia.org/wiki/Correlation', 'source': None},
                                         {'title': 'Variance', 'url': 'https://en.wikipedia.org/wiki/Variance', 'source': None},
                                         {'title': 'Regression', 'url': 'https://en.wikipedia.org/wiki/Regression', 'source': 's1'},
                                         {'title': 'Galton board', 'source': None}]
        store.save_request(record, TESTER)
        return rid

    def add(self, rid, *titles):
        return call(server.api_request_add, rid, body={'titles': list(titles)})

    def test_suggested_sources_are_added_together_and_the_outline_remade_once(self):
        rid = self.awaiting_with_suggestions()
        article = lambda urls: SimpleNamespace(title='Wikipedia', url=urls[0], text='An article is ' * 400)
        outlines = []
        real_outline = generate.make_outline
        with patch.object(server.builds, '_first_readable', side_effect=article) as read, \
                patch.object(generate, 'make_outline', side_effect=lambda *a, **k: outlines.append(1) or real_outline(*a, **k)):
            self.add(rid, 'Correlation', 'Variance', 'Correlation')
            record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        self.assertEqual([c.args[0] for c in read.call_args_list], [['https://en.wikipedia.org/wiki/Correlation'], ['https://en.wikipedia.org/wiki/Variance']])
        self.assertEqual(len(outlines), 1)
        bundle = json.loads(store.load_request(rid, TESTER)['paper']['text'])['lemma_sources']
        self.assertEqual([(s['id'], s['title']) for s in bundle][-2:], [('s2', 'Correlation'), ('s3', 'Variance')])
        self.assertEqual(store.load_request(rid, TESTER)['pending'], [])

    def test_only_a_suggested_uncovered_source_can_be_added_at_outline_review(self):
        rid = self.awaiting_with_suggestions()
        for title in ('Regression', 'Galton board', 'Anything else'):  # covered already, no article, not suggested
            with self.assertRaises(server.ApiError) as e:
                self.add(rid, 'Correlation', title)
            self.assertEqual((e.exception.status, e.exception.message), (400, "That isn't one of the suggested sources."))
        with self.assertRaises(server.ApiError) as e:
            self.add(rid)
        self.assertEqual((e.exception.status, e.exception.message), (400, 'Choose at least one source to add.'))
        record = store.load_request(rid, TESTER)
        record['paper']['text'] = json.dumps({'lemma_sources': [{'id': f's{i}', 'title': f'S{i}', 'text': 'x'} for i in range(1, 10)]})
        store.save_request(record, TESTER)
        with self.assertRaises(server.ApiError) as e:  # nine sources: room for one more, not two
            self.add(rid, 'Correlation', 'Variance')
        self.assertEqual((e.exception.status, e.exception.message), (400, 'A lesson takes at most 10 sources.'))
        record['status'] = 'done'
        store.save_request(record, TESTER)
        with self.assertRaises(server.ApiError) as e:
            self.add(rid, 'Correlation')
        self.assertEqual(e.exception.status, 409)

    def test_a_source_that_cant_be_added_is_a_warning_and_the_outline_is_still_remade(self):
        rid = self.awaiting_with_suggestions()
        with patch.object(server.builds, '_first_readable', side_effect=ingest.IngestError('Blocked by the site.')):
            self.add(rid, 'Correlation')
            record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        self.assertIn("Couldn't add Correlation: Blocked by the site.", record['warnings'])

    def test_brought_sources_are_outlined_with_what_they_build_on(self):
        found = {'subjects': [{'title': 'Mean', 'url': 'https://en.wikipedia.org/wiki/Mean', 'need': 4.5, 'relation': 'prerequisite'}], 'not_covered': []}
        seen = []

        def outline(job, provider, text, level, search=None):
            seen.append(search)
            raise generate.GenerationError('stop here')
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)), \
                patch.object(server.builds.search, 'source_subjects', return_value=found) as step, patch.object(generate, 'make_outline', side_effect=outline):
            rid = self.create()
            self.assertEqual(self.settled(rid)['status'], 'error')
            sources, level, field = step.call_args.args[1:]
            self.assertEqual((sources[0]['title'], level), ('Galton', 'beginner'))
            self.assertEqual(seen[0]['query'], None)
            self.assertEqual(seen[0]['subjects'], found['subjects'])
            self.assertEqual(seen[0]['field'], field or None)
            call(server.api_request_retry, rid)
            self.settled(rid)
        self.assertEqual(step.call_count, 1)  # kept with the request: a retry doesn't ask again
        self.assertEqual(seen[1], seen[0])

    def test_a_lesson_from_a_search_doesnt_work_out_what_its_sources_build_on(self):
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)), \
                patch.object(server.builds.search, 'source_subjects') as step, \
                patch.object(generate, 'make_outline', side_effect=generate.GenerationError('stop here')):
            self.settled(call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper', 'title': 'Paper'}], 'search': {'query': 'Why?'}})['id'])
        step.assert_not_called()

    def test_when_what_brought_sources_build_on_cant_be_worked_out_the_outline_waits(self):
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)), \
                patch.object(server.builds.search, 'source_subjects', side_effect=server.builds.search.SearchError("Couldn't work out what your sources build on just now.")):
            record = self.settled(self.create())
        self.assertEqual((record['status'], record['error']), ('error', "Couldn't work out what your sources build on just now."))
        self.assertEqual({s['id']: s['state'] for s in record['steps']}['subjects'], 'failed')

    def test_a_request_without_a_level_is_for_a_beginner_and_an_unknown_one_is_refused(self):
        self.assertEqual(call(server.api_status)['level'], 'beginner')
        with self.assertRaises(server.ApiError) as e:
            call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper'}], 'level': 'expert'})
        self.assertEqual((e.exception.status, e.exception.message), (400, 'Choose a level: Beginner, Intermediate, Advanced.'))

    def test_without_jev_no_build_is_started_or_saved(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}), patch.object(server.builds, '_first_readable') as read:
            with self.assertRaises(server.ApiError) as raised:
                self.create()
        self.assertEqual(raised.exception.status, 503)
        self.assertIn('TYPESAFE_API_KEY', raised.exception.message)
        read.assert_not_called()
        self.assertEqual(call(server.api_requests), [])

    def test_a_built_lesson_carries_its_category(self):
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://example.org/paper', text=SOURCE)):
            rid = self.create()
            outline = self.settled(rid)
        call(server.api_request_outline, rid, body={'outline': outline['outline']})
        done = self.settled(rid)
        self.assertEqual(done['status'], 'done', done.get('error'))
        self.assertEqual(store.load_lesson(rid, TESTER)[0]['category']['model'], 'jev-test')

    def test_sources_are_read_at_the_same_time_and_keep_their_order(self):
        def slow(urls):
            time.sleep(.4 if 'a.example' in urls[0] else .1)  # the first source finishes last
            return SimpleNamespace(title=urls[0], url=urls[0], text=SOURCE)
        sources = [{'url': f'https://{c}.example', 'title': c} for c in 'abc']
        start = time.monotonic()
        with patch.object(server.builds, '_first_readable', side_effect=slow):
            record = self.settled(call(server.api_request_create, body={'sources': sources})['id'])
        self.assertLess(time.monotonic() - start, .9)  # one after another would take at least 0.6s of reading alone
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        bundle = json.loads(store.load_request(record['id'], TESTER)['paper']['text'])['lemma_sources']
        self.assertEqual([(s['id'], s['url']) for s in bundle], [('s1', 'https://a.example'), ('s2', 'https://b.example'), ('s3', 'https://c.example')])

    def test_search_runs_in_the_background_and_reports_progress(self):
        from lemma import search
        search._cache.clear()
        release = threading.Event()

        def slow(query, on_progress=None, extra=(), field=None, level=None, missing=()):
            on_progress({'services': {'Wikipedia': 'done', 'OpenAlex': 'searching'}, 'found': {'Wikipedia': 1},
                         'to_check': 0, 'checked': 0, 'readable': 0})
            release.wait(5)
            return {'query': query, 'kind': 'concept', 'results': [], 'unavailable': [], 'checked_at': time.time()}

        # What to look up is tested in SearchTests; here the provider names nothing Wikipedia knows.
        with patch.object(search, '_search', side_effect=slow), patch.object(search, 'terms', return_value=['Free will'] * 5), \
                patch.object(search, 'resolve', return_value=[]):
            started = call(server.api_search, body={'query': '  free   will '})
            self.assertFalse(started['done'])
            self.assertEqual(started['query'], 'free will')
            for _ in range(100):
                status = call(server.api_search_status, started['id'])
                if (status['progress'] or {}).get('services'):  # past working out the field and what to look up
                    break
                time.sleep(.01)
            self.assertEqual(status['progress']['services']['OpenAlex'], 'searching')  # seen while it runs
            release.set()
            for _ in range(1000):  # up to 10 s: a build settles in the background, slower when the whole suite runs
                status = call(server.api_search_status, started['id'])
                if status['done']:
                    break
                time.sleep(.01)
            self.assertEqual((status['done'], status['error'], status['result']['query']), (True, '', 'free will'))
            again = call(server.api_search, body={'query': 'Free will'})  # a recent search is answered at once
            self.assertEqual((again['done'], again['result']['query']), (True, 'free will'))
        with self.assertRaises(server.ApiError):
            call(server.api_search, body={'query': '   '})
        with self.assertRaises(server.ApiError):
            call(server.api_search_status, '0123456789ab')

    def test_uploaded_files_and_links_make_one_lesson_in_the_order_given(self):
        pid = 'upload1'
        server.builds.PAPERS[pid] = {'text': SOURCE, 'title': 'My chapter', 'url': '', 'kind': 'pdf', 'pages': 3, 'owner': TESTER}
        self.addCleanup(server.builds.PAPERS.pop, pid, None)
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='https://b.example', text=SOURCE)) as read:
            rid = call(server.api_request_create, body={'sources': [{'paper_id': pid}, {'url': 'https://b.example', 'title': 'b'}]})['id']
            record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        read.assert_called_once_with(['https://b.example'])  # the file is never fetched
        bundle = json.loads(store.load_request(rid, TESTER)['paper']['text'])['lemma_sources']
        self.assertEqual([(s['id'], s['title']) for s in bundle], [('s1', 'My chapter'), ('s2', 'Galton')])
        self.assertEqual(bundle[0]['text'], SOURCE)

    def test_a_retry_still_has_an_uploaded_file_after_memory_lets_it_go(self):
        server.builds.PAPERS['upload2'] = {'text': SOURCE, 'title': 'Notes', 'url': '', 'kind': 'text', 'pages': 0, 'owner': TESTER}
        with patch.object(server.builds, '_first_readable', side_effect=ingest.IngestError('blocked')):
            rid = call(server.api_request_create, body={'sources': [{'paper_id': 'upload2'}, {'url': 'https://a.example'}]})['id']
            server.builds.PAPERS.pop('upload2')
            self.settled(rid)
            disk = store.load_request(rid, TESTER)
            disk['status'], disk['paper'] = 'running', None
            store.save_request(disk, TESTER)
            generate.JOBS.pop(rid)
            call(server.api_request_retry, rid)
            record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        self.assertEqual([s['title'] for s in json.loads(store.load_request(rid, TESTER)['paper']['text'])['lemma_sources']], ['Notes'])

    def test_a_file_someone_else_uploaded_cant_be_a_source(self):
        server.builds.PAPERS['theirs'] = {'text': SOURCE, 'title': 'Theirs', 'url': '', 'kind': 'pdf', 'pages': 1, 'owner': 'someone-else'}
        self.addCleanup(server.builds.PAPERS.pop, 'theirs', None)
        with self.assertRaises(server.ApiError) as raised:
            call(server.api_request_create, body={'sources': [{'paper_id': 'theirs'}]})
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(call(server.api_requests), [])

    def test_partial_failure_restart_and_retry(self):
        server.core._provider.return_value.source_id = 's2'
        with patch.object(server.builds, '_first_readable', side_effect=lambda urls: _raise(ingest.IngestError('blocked')) if 'a.example' in urls[0] else SimpleNamespace(title='Galton', url='', text=SOURCE)):
            rid = call(server.api_request_create, body={'sources': [{'url': 'https://a.example', 'title': 'Blocked'}, {'url': 'https://b.example', 'title': 'Readable'}]})['id']
            record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        self.assertIn('Blocked', record['warnings'][0])
        disk = store.load_request(rid, TESTER)
        disk['status'] = 'running'
        store.save_request(disk, TESTER)
        generate.JOBS.pop(rid)
        self.assertEqual(call(server.api_request, rid)['status'], 'interrupted')
        call(server.api_request_retry, rid)
        self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
        call(server.api_request_cancel, rid)
        self.assertEqual(call(server.api_request, rid)['status'], 'cancelled')
        call(server.api_request_delete, rid)
        self.assertFalse(store.request_path(rid, TESTER).exists())

    # ------------------------------------------------------------ sources that couldn't be read

    BLOCKED = 'https://blocked.example/b'

    def partly_read(self):
        """A build of two sources, the second of which couldn't be read, at outline review. Reading it again fails while
        self.blocked holds and works once it's cleared; every link read is in self.reads."""
        self.blocked, self.reads = {self.BLOCKED}, []

        def read(urls):
            self.reads.append(urls[0])
            if urls[0] in self.blocked:
                raise ingest.IngestError('The site refused the download.')
            return SimpleNamespace(title=urls[0].split('/')[2], url=urls[0], text=SOURCE)
        reader = patch.object(server.builds, '_first_readable', side_effect=read)
        reader.start()
        self.addCleanup(reader.stop)
        rid = call(server.api_request_create, body={'sources': [{'url': 'https://ok.example/a', 'title': 'Readable'},
                                                     {'url': self.BLOCKED, 'title': 'Blocked'}]})['id']
        record = self.settled(rid)
        self.assertEqual(record['status'], 'awaiting_outline', record.get('error'))
        self.assertEqual(record['excluded'], [{'source': 2, 'title': 'Blocked', 'reason': 'The site refused the download.'}])
        self.assertEqual(record['warnings'], ['Excluded Blocked: The site refused the download.'])
        return rid, record

    def stopped_with_approved_outline(self, rid, record):
        call(server.api_request_outline, rid, body={'outline': record['outline']})
        self.assertEqual(self.settled(rid)['status'], 'done')
        with server.builds._requests_lock:  # the job's thread saves once more after it settles: it mustn't land after this edit
            generate.JOBS.pop(rid, None)
        disk = store.load_request(rid, TESTER)
        disk.update(status='error', error='Something went wrong.')
        store.save_request(disk, TESTER)

    def bundle(self, rid):
        return [(s['id'], s['title']) for s in json.loads(store.load_request(rid, TESTER)['paper']['text'])['lemma_sources']]

    def retry(self, rid, mode=None):
        call(server.api_request_retry, rid, body={'mode': mode} if mode else {})
        return self.settled(rid)

    def test_the_choice_says_which_sources_couldnt_be_read_and_continuing_builds_without_them(self):
        rid, record = self.partly_read()
        self.stopped_with_approved_outline(rid, record)
        self.assertEqual(call(server.api_request, rid)['resume']['excluded'], ['Blocked'])
        self.blocked.clear()  # the site works again, but continuing keeps the sources its concepts were built from
        self.reads.clear()
        done = self.retry(rid, 'continue')
        self.assertEqual(done['status'], 'done', done.get('error'))
        self.assertEqual(self.reads, [])
        self.assertEqual(self.bundle(rid), [('s1', 'ok.example')])
        self.assertEqual(done['warnings'], ['Excluded Blocked: The site refused the download.'])

    def test_starting_over_reads_the_sources_that_couldnt_be_read_again(self):
        rid, record = self.partly_read()
        self.stopped_with_approved_outline(rid, record)
        self.blocked.clear()
        self.reads.clear()
        with patch.object(server.builds.search, 'source_subjects', return_value={'subjects': [], 'not_covered': []}) as subjects, \
                patch.object(server.builds.categorize, 'categorize', wraps=server.builds.categorize.categorize) as categorized:
            review = self.retry(rid, 'start_over')
        self.assertEqual(review['status'], 'awaiting_outline', review.get('error'))
        self.assertEqual(self.reads, [self.BLOCKED])  # only the one that couldn't be read; the others are kept as read
        self.assertEqual(self.bundle(rid), [('s1', 'ok.example'), ('s2', 'blocked.example')])  # in the order chosen
        self.assertEqual((review['warnings'], review['excluded']), ([], []))
        self.assertEqual((subjects.call_count, categorized.call_count), (1, 1))  # worked out again, for the sources now read
        steps = {s['id']: s for s in review['steps']}
        self.assertEqual((steps['s2']['label'], steps['s2']['state']), ('Reading source 2 again: Blocked', 'done'))

    def test_a_source_that_still_cant_be_read_stays_a_warning(self):
        rid, record = self.partly_read()
        self.stopped_with_approved_outline(rid, record)
        category = store.load_request(rid, TESTER)['category']
        self.reads.clear()
        self.blocked.add(self.BLOCKED)
        with patch.object(server.builds.search, 'source_subjects') as subjects:
            review = self.retry(rid, 'start_over')
        self.assertEqual(review['status'], 'awaiting_outline', review.get('error'))
        self.assertEqual(self.reads, [self.BLOCKED])
        self.assertEqual(self.bundle(rid), [('s1', 'ok.example')])
        self.assertEqual(review['warnings'], ['Excluded Blocked: The site refused the download.'])
        self.assertEqual(review['excluded'][0]['source'], 2)
        subjects.assert_not_called()  # the sources didn't change, so neither did what they build on
        self.assertEqual(store.load_request(rid, TESTER)['category'], category)

    def test_any_retry_that_proposes_an_outline_reads_them_again(self):
        rid, _ = self.partly_read()
        call(server.api_request_cancel, rid)  # cancelled at outline review: no approved outline, so no choice
        self.blocked.clear()
        self.reads.clear()
        self.assertEqual(self.retry(rid)['status'], 'awaiting_outline')
        self.assertEqual(self.reads, [self.BLOCKED])
        self.assertEqual(self.bundle(rid), [('s1', 'ok.example'), ('s2', 'blocked.example')])

    def test_a_source_added_at_outline_review_never_takes_an_unread_sources_place(self):
        rid, _ = self.partly_read()
        record = store.load_request(rid, TESTER)
        record['outline']['subjects'] = [{'title': 'Variance', 'url': 'https://en.wikipedia.org/wiki/Variance', 'source': None}]
        store.save_request(record, TESTER)
        self.add(rid, 'Variance')
        self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
        self.assertEqual(self.bundle(rid), [('s1', 'ok.example'), ('s3', 'Variance')])  # s2 stays the source that couldn't be read
        call(server.api_request_cancel, rid)
        self.blocked.clear()
        self.retry(rid)
        self.assertEqual(self.bundle(rid), [('s1', 'ok.example'), ('s2', 'blocked.example'), ('s3', 'Variance')])

    # ------------------------------------------------------------ a build of one source kept as plain text

    def one_file(self):
        """A build made from one uploaded file by `paper_id`, which keeps it as plain text, at outline review with a
        suggested source to add (an assumed subject's article)."""
        server.builds.PAPERS['single'] = {'text': SOURCE, 'title': 'My chapter', 'url': '', 'kind': 'pdf', 'pages': 3, 'owner': TESTER}
        self.addCleanup(server.builds.PAPERS.pop, 'single', None)
        rid = call(server.api_request_create, body={'paper_id': 'single'})['id']
        self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
        record = store.load_request(rid, TESTER)
        self.assertFalse(record['paper']['text'].startswith('{'))  # plain text, not a bundle
        record['outline']['subjects'] = [{'title': f'Subject {i}', 'url': f'https://en.wikipedia.org/wiki/S{i}', 'source': None} for i in range(1, 11)]
        store.save_request(record, TESTER)
        return rid

    def test_a_suggested_source_can_be_added_to_a_build_of_one_file(self):
        rid = self.one_file()
        article = lambda urls: SimpleNamespace(title='Wikipedia', url=urls[0], text='An article is ' * 400)
        with patch.object(server.builds, '_first_readable', side_effect=article):
            self.add(rid, 'Subject 1')
            review = self.settled(rid)
        self.assertEqual(review['status'], 'awaiting_outline', review.get('error'))
        bundle = json.loads(store.load_request(rid, TESTER)['paper']['text'])['lemma_sources']
        self.assertEqual([(s['id'], s['title']) for s in bundle], [('s1', 'My chapter'), ('s2', 'Subject 1')])
        self.assertEqual(bundle[0]['text'], SOURCE)  # the file, unchanged, is now the first of the lesson's sources
        self.assertIn('never by source', server.core._provider.return_value.tasks['outline'])  # outlined as a lesson of several sources
        call(server.api_request_outline, rid, body={'outline': review['outline']})
        done = self.settled(rid)
        self.assertEqual(done['status'], 'done', done.get('error'))
        lesson, source = store.load_lesson(rid, TESTER)
        self.assertEqual([s['title'] for s in lesson['sources']], ['My chapter', 'Subject 1'])
        self.assertEqual(L.check_lesson(lesson, source), [])

    def test_one_file_counts_toward_the_limit_of_ten_sources(self):
        rid = self.one_file()
        with self.assertRaises(server.ApiError) as e:
            self.add(rid, *[f'Subject {i}' for i in range(1, 11)])  # the file and 10 more would be 11
        self.assertEqual((e.exception.status, e.exception.message), (400, 'A lesson takes at most 10 sources.'))
        with patch.object(server.builds, '_first_readable', side_effect=lambda urls: SimpleNamespace(title='W', url=urls[0], text='An article is ' * 400)):
            self.add(rid, *[f'Subject {i}' for i in range(1, 10)])  # the file and 9 more make 10
            self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')

    def test_all_failed_validation_and_isolation(self):
        with patch.object(server.builds, '_first_readable', side_effect=ingest.IngestError('unreadable')):
            rid = self.create()
            self.assertEqual(self.settled(rid)['status'], 'error')
        self.assertNotIn('key', json.dumps(store.load_request(rid, TESTER)).lower())
        with self.assertRaises(server.ApiError):
            call(server.api_request_create, body={'sources': []})
        with self.assertRaises(server.ApiError):
            call(server.api_request_create, body={'sources': [{'url': 'file:///secret'}]})
        sign_in('different')
        with self.assertRaises(server.ApiError):
            call(server.api_request, rid)
        self.assertEqual(call(server.api_requests), [])

    def test_http_outline_body_and_credential_free_storage(self):
        httpd = server.make_server(0, exact=True)
        cookie = session_cookie()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        def request(method, path, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', httpd.server_address[1])
            connection.request(method, path, json.dumps(body) if body else None,
                               {'Content-Type': 'application/json', 'X-Lemma-Key': 'test-secret-never-store', 'Cookie': cookie})
            response = connection.getresponse()
            data = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200, data)
            return data
        try:
            with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='', text=SOURCE)):
                rid = request('POST', '/api/requests', {'sources': [{'url': 'https://example.org'}]})['id']
                outline = self.settled(rid)['outline']
            request('POST', f'/api/requests/{rid}/outline', {'outline': outline})
            self.assertEqual(self.settled(rid)['status'], 'done')
            self.assertNotIn('test-secret-never-store', store.request_path(rid, TESTER).read_text())
            self.assertEqual(request('GET', f'/api/requests/{rid}')['status'], 'done')
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_provider_error_cannot_persist_echoed_key(self):
        with patch.object(server.builds, '_first_readable', return_value=SimpleNamespace(title='Galton', url='', text=SOURCE)), patch.object(generate, 'make_outline', side_effect=ProviderError('Invalid key secret-test-key')):
            rid = call(server.api_request_create, body={'sources': [{'url': 'https://example.org/paper', 'title': 'Paper'}], 'topic': 'Regression'},
                       headers={'X-Lemma-Key': 'secret-test-key'})['id']
            self.assertEqual(self.settled(rid)['status'], 'error')
        self.assertNotIn('secret-test-key', store.request_path(rid, TESTER).read_text())
        self.assertIn('[redacted]', call(server.api_request, rid)['error'])

    def test_long_source_text_is_not_rejected_or_truncated(self):
        text = 'Full source content.\n' * 80_000
        paper = ingest.from_bytes(text.encode(), filename='long.txt')
        self.assertGreater(len(paper.text), 1_500_000)
        self.assertEqual(paper.text, text.strip())

        with patch.object(server.builds, '_first_readable', return_value=paper), patch.object(generate, 'make_outline', return_value={}) as outline:
            rid = self.create()
            self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
            supplied = json.loads(outline.call_args.args[2])['lemma_sources'][0]['text']
            self.assertEqual(supplied, paper.text)

        with patch.object(server.builds, '_paper', return_value={'text': paper.text, 'title': 'Long upload', 'url': '', 'owner': TESTER}), patch.object(generate, 'make_outline', return_value={}) as outline:
            rid = call(server.api_request_create, body={'paper_id': 'upload'})['id']
            self.assertEqual(self.settled(rid)['status'], 'awaiting_outline')
            self.assertEqual(outline.call_args.args[2], paper.text)
