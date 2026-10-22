"""Multi-source grounding and observable background job behavior."""
import copy
import json
import unittest

from test_lemma import EXAMPLE, SOURCE, FakeProvider, wait
from lemma import generate, ingest, lesson as L, search
from lemma.llm import Reply
import fakejev  # noqa: E402,F401  Jev is essential, so every search and build asks this stand-in


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

    def test_concepts_from_several_sources_are_ordered_by_what_they_rely_on(self):
        provider = MultiSourceProvider()
        outline = wait(generate.start(generate.Job('outline'), generate.make_outline, provider, self.bundle, '')).result
        self.assertIn('never by source', provider.tasks['outline'])
        ids = [c['id'] for c in outline['concepts']]
        self.assertEqual(generate.check_outline(outline, self.bundle, require_needs=True), [])
        swapped = copy.deepcopy(outline)
        swapped['concepts'].reverse()
        self.assertTrue(any('comes later' in p for p in generate.check_outline(swapped, self.bundle)))
        self.assertEqual([c['id'] for c in generate.order_outline(swapped)['concepts']], ids)
        job = wait(generate.start(generate.Job('build'), generate.build_lesson, provider,
                                  {'text': self.bundle, 'title': 'Combined', 'url': ''}, swapped, ''))
        self.assertEqual(job.status, 'done', job.error)
        self.assertEqual([c['id'] for c in job.result['concepts']], ids)
        self.assertIn('never rely on an idea from a', provider.tasks[ids[-1]])

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

    def test_recommendations_follow_what_the_search_is_for(self):
        from unittest.mock import patch
        overview = {'kind': 'overview', 'title': 'Overview', 'url': 'https://example.org/overview'}
        explainers = [{'kind': 'explainer', 'title': f'Chapter {i}', 'url': f'https://example.org/c{i}'} for i in range(2)]
        papers = [{'kind': 'paper', 'title': f'Paper {i}', 'url': f'https://example.org/{i}'} for i in range(4)]

        def run(query):
            with patch.object(search, 'wikipedia', return_value=[dict(overview)]), patch.object(search, 'sep', return_value=[dict(e) for e in explainers]), patch.object(search, 'libretexts', return_value=[]), patch.object(search, 'openalex', return_value=[dict(p) for p in papers]), patch.object(search, 'europepmc', return_value=[]), patch.object(search, 'arxiv', return_value=[]), patch.object(ingest, 'first_readable', side_effect=lambda urls, **kw: ingest.Paper(text='word ' * 1000, title='T', url=urls[0], kind='html')):
                return search._search(query)

        # An idea: the overview and an explanation lead, with one paper for evidence.
        concept = run('bayes theorem')
        self.assertEqual(concept['kind'], 'concept')
        self.assertEqual([r['kind'] for r in concept['results']][:3], ['overview', 'explainer', 'explainer'])
        self.assertEqual([r['title'] for r in concept['results'] if r['recommended']], ['Overview', 'Chapter 0', 'Paper 0'])
        # A particular paper: papers lead, with an overview for context.
        paper = run('Galton 1886 regression towards mediocrity')
        self.assertEqual(paper['kind'], 'paper')
        self.assertEqual(paper['results'][0]['kind'], 'paper')
        self.assertEqual([r['title'] for r in paper['results'] if r['recommended']], ['Paper 0', 'Paper 1', 'Overview'])

    def test_an_article_named_after_a_paper_is_not_the_paper(self):
        from unittest.mock import patch
        article = {'kind': 'overview', 'title': 'Attention Is All You Need', 'url': 'https://en.wikipedia.org/wiki/Attention_Is_All_You_Need'}
        paper = {'kind': 'paper', 'title': 'Attention Is All You Need', 'url': 'https://arxiv.org/abs/1706.03762', 'authors': 'Ashish Vaswani'}
        with patch.object(search, 'wikipedia', return_value=[article]), patch.object(search, 'sep', return_value=[]), patch.object(search, 'libretexts', return_value=[]), patch.object(search, 'openalex', return_value=[]), patch.object(search, 'europepmc', return_value=[]), patch.object(search, 'arxiv', return_value=[paper]), patch.object(ingest, 'first_readable', side_effect=lambda urls, **kw: ingest.Paper(text='word ' * 1000, title='T', url=urls[0], kind='html')):
            results = search._search('Vaswani et al attention is all you need 2017')['results']
        self.assertEqual([r['kind'] for r in results], ['paper', 'overview'])

    def test_what_a_search_is_for(self):
        for q in ('regression to the mean', 'free will', 'chemical equilibrium'):
            self.assertEqual(search.query_kind(q), 'concept', q)
        for q in ('10.1093/ije/dyh299', 'arXiv 1706.03762', 'Vaswani et al attention', 'Galton 1886',
                  '"Attention is all you need"', 'a national experiment reveals where a growth mindset improves achievement'):
            self.assertEqual(search.query_kind(q), 'paper', q)

    def test_a_europe_pmc_copy_makes_a_pmc_paper_readable(self):
        from unittest.mock import patch
        blocked = {'kind': 'paper', 'title': 'Same paper', 'url': 'https://www.ncbi.nlm.nih.gov/pmc/articles/123',
                   'urls': ['https://publisher.example/x.pdf', 'https://www.ncbi.nlm.nih.gov/pmc/articles/123']}
        xml = ingest.europe_pmc_full_text('PMC123')
        copy_ = {'kind': 'paper', 'title': 'Same paper.', 'url': xml, 'urls': [xml]}
        def fetch(url, **kwargs):
            if url != xml:
                raise ingest.IngestError('The site answered 403 Forbidden.')
            return ingest.Paper(text='word ' * 1000, title='T', url=url, kind='xml')
        with patch.object(search, 'wikipedia', return_value=[]), patch.object(search, 'sep', return_value=[]), patch.object(search, 'libretexts', return_value=[]), patch.object(search, 'openalex', return_value=[blocked]), patch.object(search, 'europepmc', return_value=[copy_]), patch.object(search, 'arxiv', return_value=[]), patch.object(ingest, 'from_url', side_effect=fetch):
            [result] = search._search('same paper')['results']  # listed once
        self.assertTrue(result['available'])
        self.assertEqual(result['url'], xml)  # Lemma reads the open XML…
        self.assertEqual(result['link'], 'https://europepmc.org/article/PMC/PMC123')  # …the learner opens the article page

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
        with patch.object(search, 'wikipedia', return_value=[]), patch.object(search, 'openalex', return_value=results), patch.object(search, 'arxiv', return_value=[]), patch.object(search, 'sep', return_value=[]), patch.object(search, 'libretexts', return_value=[]), patch.object(search, 'europepmc', return_value=[]), patch.object(ingest, 'from_url', side_effect=fetch):
            result = search._search('topic')
        alternate, blocked, abstract = result['results']  # readable papers come first
        self.assertFalse(blocked['recommended'])
        self.assertIn('403', blocked['availability_error'])
        self.assertFalse(abstract['recommended'])
        self.assertFalse(abstract['available'])
        self.assertTrue(alternate['recommended'])
        self.assertEqual(alternate['url'], 'https://example.org/full')
        self.assertEqual(alternate['urls'][0], alternate['url'])

    def test_readable_papers_fill_the_list_before_blocked_ones(self):
        from unittest.mock import patch
        papers = [{'kind': 'paper', 'title': f'Paper {i}', 'url': f'https://example.org/{"403" if i < 8 else "full"}/{i}'} for i in range(search.CANDIDATES)]
        def fetch(url, **kwargs):
            if '/403/' in url:
                raise ingest.IngestError('The site answered 403 Forbidden.')
            return ingest.Paper(text='word ' * 1000, title='T', url=url, kind='html')
        with patch.object(search, 'wikipedia', return_value=[]), patch.object(search, 'openalex', return_value=papers), patch.object(search, 'arxiv', return_value=[]), patch.object(search, 'sep', return_value=[]), patch.object(search, 'libretexts', return_value=[]), patch.object(search, 'europepmc', return_value=[]), patch.object(ingest, 'from_url', side_effect=fetch):
            shown = search._search('topic')['results']
        # The best eight are blocked, so the readable ones further down take their places.
        self.assertEqual([r['title'] for r in shown], [f'Paper {i}' for i in range(8, 14)])
        self.assertTrue(all(r['available'] for r in shown))

    def test_availability_is_rechecked_after_cache_expires(self):
        from unittest.mock import patch
        search._cache.clear()
        now = 1000
        def results(query, on_progress=None, extra=(), field=None, level=None, missing=()):
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
