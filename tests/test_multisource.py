"""Multi-source grounding and observable background job behavior."""
import copy
import json
import unittest

from test_lemma import EXAMPLE, SOURCE, FakeProvider, wait
from lemma import generate, ingest, lesson as L, search
from lemma.llm import Reply


class MultiSourceProvider(FakeProvider):
    def reply(self, task, turn):
        reply = super().reply(task, turn)
        obj = json.loads(reply.text.removeprefix('```json\n').removesuffix('\n```'))
        blocks = obj['primer'] if 'primer' in obj else [obj['understand']]
        for block in blocks:
            sid = getattr(self, 'source_id', 's1')
            block['source_ids'] = [sid]
            if block.get('quote'):
                block['source_id'] = sid
        return Reply(json.dumps(obj), reply.stop_reason)


class MultiSourceTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.dumps({'lemma_sources': [
            {'id': 's1', 'title': 'Galton', 'url': '', 'text': SOURCE},
            {'id': 's2', 'title': 'Different paper', 'url': '', 'text': 'Other evidence about unrelated ideas.'},
        ]})

    def test_combined_generation_and_wrong_source_rejection(self):
        provider = MultiSourceProvider()
        outline_job = wait(generate.start(generate.Job('outline'), generate.make_outline, provider, self.bundle, ''))
        self.assertEqual(outline_job.status, 'done', outline_job.error)
        job = wait(generate.start(generate.Job('build'), generate.build_lesson, provider,
                                  {'text': self.bundle, 'title': 'Combined', 'url': ''}, outline_job.result, ''))
        self.assertEqual(job.status, 'done', job.error)
        self.assertEqual(len(job.result['sources']), 2)
        self.assertNotIn('text', job.result['sources'][0])
        self.assertFalse(L.check_lesson(job.result, self.bundle))
        bad = copy.deepcopy(job.result)
        bad['concepts'][0]['understand']['source_id'] = 's2'
        self.assertTrue(any('identified source' in p for p in L.check_lesson(bad, self.bundle)))
        bad['concepts'][0]['understand']['source_ids'] = ['nonexistent']
        self.assertTrue(any('source_ids' in p for p in L.check_lesson(bad, self.bundle)))

    def test_outline_requires_attribution(self):
        outline = wait(generate.start(generate.Job('outline'), generate.make_outline, FakeProvider(), SOURCE, '')).result
        self.assertTrue(any('source_ids' in p for p in generate.check_outline(outline, self.bundle)))

    def test_job_callbacks_cancellation_and_estimate(self):
        job = generate.Job('build')
        changes = []
        job.on_change = lambda j: changes.append(j.snapshot())
        self.assertIsNone(job.snapshot()['eta_seconds'])
        job.step('one', 'Concept 1: first', 'active')
        job.update('one', 'done')
        job.step('two', 'Concept 2: second', 'waiting')
        self.assertIsNotNone(job.snapshot()['eta_seconds'])
        self.assertEqual(len(changes), 3)
        def cancel(j):
            j.cancelled.set()
            raise generate.GenerationError('Cancelled.')
        wait(generate.start(job, cancel))
        self.assertEqual(job.status, 'cancelled')

    def test_recommendations_include_overview_and_two_papers(self):
        from unittest.mock import patch
        overview = {'kind': 'overview', 'title': 'Overview', 'url': 'https://example.org/overview'}
        papers = [{'kind': 'paper', 'title': f'Paper {i}', 'url': f'https://example.org/{i}'} for i in range(4)]
        with patch.object(search, 'wikipedia', return_value=[overview]), patch.object(search, 'openalex', return_value=papers), patch.object(search, 'arxiv', return_value=[]), patch.object(ingest, 'first_readable', side_effect=lambda urls, **kw: ingest.Paper(text='word ' * 1000, title='T', url=urls[0], kind='html')):
            result = search._search('topic')
        selected = [r for r in result['results'] if r['recommended']]
        self.assertEqual(len(selected), 3)
        self.assertEqual(selected[0]['kind'], 'overview')

    def test_blocked_and_abstract_only_sources_are_not_recommended(self):
        from unittest.mock import patch
        results = [
            {'kind': 'paper', 'title': 'Blocked', 'url': 'https://example.org/403'},
            {'kind': 'paper', 'title': 'Abstract', 'url': 'https://example.org/abstract'},
            {'kind': 'paper', 'title': 'Alternate', 'url': 'https://example.org/403',
             'urls': ['https://example.org/403', 'https://example.org/full']},
        ]
        def fetch(url, **kwargs):
            if url.endswith('/403'):
                raise ingest.IngestError('The site answered 403 Forbidden.')
            return ingest.Paper(text='word ' * (1000 if url.endswith('/full') else 20), title='T', url=url, kind='html')
        with patch.object(search, 'wikipedia', return_value=[]), patch.object(search, 'openalex', return_value=results), patch.object(search, 'arxiv', return_value=[]), patch.object(ingest, 'from_url', side_effect=fetch):
            result = search._search('topic')
        blocked, abstract, alternate = result['results']
        self.assertFalse(blocked['recommended'])
        self.assertIn('403', blocked['availability_error'])
        self.assertFalse(abstract['recommended'])
        self.assertFalse(abstract['available'])
        self.assertTrue(alternate['recommended'])
        self.assertEqual(alternate['url'], 'https://example.org/full')
        self.assertEqual(alternate['urls'][0], alternate['url'])

    def test_availability_is_rechecked_after_cache_expires(self):
        from unittest.mock import patch
        search._cache.clear()
        now = 1000
        def results(query):
            return {'query': query, 'results': [], 'unavailable': [], 'checked_at': now}
        with patch.object(search.time, 'time', side_effect=lambda: now), patch.object(search, '_search', side_effect=results) as run:
            search.search('cache-test')
            now += 1
            search.search('cache-test')
            self.assertEqual(run.call_count, 1)
            now += search.CACHE_TTL
            search.search('cache-test')
            self.assertEqual(run.call_count, 2)
        search._cache.clear()
