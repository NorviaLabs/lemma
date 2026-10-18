"""Finding something to learn from: search a topic across open scholarly indexes.

Search words go to six services, none of which needs an account or key; source sites are then
contacted to verify readable full text, and only verified readable sources are recommended.
Wikipedia returns one overview article. The Stanford Encyclopedia of Philosophy and LibreTexts
return entries and textbook chapters that explain a concept in depth. OpenAlex returns open-access
papers ranked by relevance and citations, Europe PMC returns biomedical papers whose full text it
serves openly, and arXiv returns preprints.

A search for a concept leads with the overview and explanations; a search for a paper leads with papers.
When the server has a TypeSafe key, Jev judges how well each result would teach what was searched for, which
orders each group and decides which results are recommended (see judge()); otherwise the title match does.
"""

from __future__ import annotations

import html
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import ingest, jev, logs
from .ingest import USER_AGENT

TIMEOUT = 12
MAX_QUERY = 200
CHECK_TIMEOUT = 5  # seconds for one link while checking a result
CHECK_BUDGET = 12  # seconds for all of one result's links together
CACHE_TTL = 300
PAPERS = 6       # papers shown from OpenAlex and Europe PMC
REVIEW_BOOST = 1.5  # how much a review article is preferred when the search is for an idea
CANDIDATES = 15  # ranked OpenAlex papers checked to find them: many publishers block automatic downloads
SEP = "Stanford Encyclopedia of Philosophy"
SOURCES = ("Wikipedia", SEP, "LibreTexts", "OpenAlex", "Europe PMC", "arXiv")
EXPLAINER_MATCH = 2  # encyclopedias and textbooks answer every search, so their entry must be about it by title
LIBRETEXTS = ("chem",)  # LibreTexts libraries whose search answers without a developer token; the others ask for one


class SearchError(Exception):
    pass


MAX_WAIT = 15  # seconds we'll wait once when a service asks us to slow down


def _get(url: str, retry: bool = True) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml;q=0.9, text/html;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        if e.code != 429 or not retry:
            raise
        try:
            wait = float(e.headers.get("Retry-After") or json.loads(e.read(2048) or b"{}").get("retryAfter") or 5)
        except (ValueError, AttributeError):
            wait = 5
        if wait > MAX_WAIT:
            raise
        time.sleep(wait)
        return _get(url, retry=False)


def _plain(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _authors(names: list[str]) -> str:
    names = [n for n in names if n]
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


def _abstract(inverted: dict | None) -> str:
    """OpenAlex stores abstracts as word → positions."""
    if not inverted:
        return ""
    words = sorted((p, w) for w, ps in inverted.items() for p in ps)
    return " ".join(w for _, w in words)


PMC_PAGE = re.compile(r"ncbi\.nlm\.nih\.gov/pmc/articles/(?:PMC)?(\d+)", re.I)


def _with_europe_pmc(url: str) -> list[str]:
    m = PMC_PAGE.search(url)
    return [ingest.europe_pmc_full_text("PMC" + m.group(1)), url] if m else [url]


DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;])")
ARXIV_ID = re.compile(r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b")


def search_words(query: str) -> str:
    """A search for a paper without what an index can't match in a title: years and "et al"."""
    return re.sub(r"\s+", " ", re.sub(r"\bet al\b\.?|\b(?:1[5-9]|20)\d{2}\b", " ", query, flags=re.I)).strip() or query


def openalex(query: str, n: int = CANDIDATES) -> list[dict]:
    words, concept = _words(query), query_kind(query) == "concept"
    if doi := DOI.search(query):  # a DOI names one work: look it up rather than search for it
        works = [json.loads(_get("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi.group(1), safe="/")))]
        return _openalex_results({"results": [w | {"relevance_score": 1} for w in works]}, n)
    params = {
        # An idea is searched as a phrase, so "free will" doesn't bring back "model-free control".
        "search": f'"{" ".join(words)}"' if concept and len(words) > 1 else search_words(query),
        "filter": "is_oa:true,type:article|preprint|review",
        "per-page": "25",
        "select": "id,type,display_name,publication_year,authorships,primary_location,best_oa_location,locations,cited_by_count,abstract_inverted_index,relevance_score",
    }
    return _openalex_results(json.loads(_get("https://api.openalex.org/works?" + urllib.parse.urlencode(params))), n, concept)


def _openalex_results(data: dict, n: int, concept: bool = False) -> list[dict]:
    out = []
    for w in data.get("results") or []:
        # Every open copy, best first: if one can't be read (a scan, a blocked download), Lemma tries the next.
        locs = [w.get("best_oa_location") or {}] + [l for l in w.get("locations") or [] if l.get("is_oa")]
        urls = [u for l in locs for u in (l.get("pdf_url"), l.get("landing_page_url"))
                if u and re.match(r"^https?://[^\s<>\"]+$", u) and "orcid.org" not in u]
        # PMC's pages challenge anything that isn't a browser; Europe PMC serves the open-access ones.
        urls = [v for u in urls for v in _with_europe_pmc(u)]
        # PDFs and full-text archives before DOI landing pages, which are often just the abstract.
        urls = sorted(dict.fromkeys(urls), key=lambda u: "doi.org/" in u)[:5]
        if not urls or not w.get("display_name"):
            continue
        venue = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        cites = int(w.get("cited_by_count") or 0)
        out.append({
            "kind": "paper", "source": "OpenAlex", "title": _plain(w["display_name"], 300),
            "authors": _authors([(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []]),
            "year": w.get("publication_year"), "venue": venue, "cited_by": cites, "url": urls[0], "urls": urls,
            "summary": _plain(_abstract(w.get("abstract_inverted_index"))),
            # Relevance first, nudged up a little by how much the field has used the paper. Someone learning an
            # idea is better served by a review, written to explain a field, than by one study within it.
            "score": float(w.get("relevance_score") or 0) * (1 + math.log10(cites + 1) / 10)
                     * (REVIEW_BOOST if w.get("type") == "review" and concept else 1),
        })
    out.sort(key=lambda r: -r["score"])
    return out[:n]


def europepmc(query: str, n: int = 4) -> list[dict]:
    """Biomedical papers with open full text, matched on their title or abstract."""
    phrase = query.replace('"', "")
    params = {"query": f'(TITLE:"{phrase}" OR ABSTRACT:"{phrase}") AND OPEN_ACCESS:y AND HAS_FT:y',
              "format": "json", "resultType": "core", "pageSize": str(n)}
    data = json.loads(_get(ingest.EUROPE_PMC + "search?" + urllib.parse.urlencode(params)))
    out = []
    for r in (data.get("resultList") or {}).get("result") or []:
        pmcid = r.get("pmcid") or ""
        if not re.fullmatch(r"PMC\d+", pmcid) or not r.get("title"):
            continue
        url = ingest.europe_pmc_full_text(pmcid)
        out.append({
            "kind": "paper", "source": "Europe PMC", "title": _plain(r["title"], 300).rstrip("."),
            "authors": _authors((r.get("authorString") or "").rstrip(".").split(", ")),
            "year": int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None,
            "venue": ((r.get("journalInfo") or {}).get("journal") or {}).get("title") or "",
            "cited_by": int(r.get("citedByCount") or 0), "url": url, "urls": [url],
            "summary": _plain(r.get("abstractText") or ""),
        })
    return out


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def match(query: str, title: str, summary: str = "") -> int:
    """How closely a result is about the search: 3 when its title holds the whole phrase, 2 when its title holds
    every word, 1 when its title and summary together do, 0 otherwise. Words are compared by their stem, so
    "causation" matches "causal", and short words like "to" and "the" are ignored."""
    query = search_words(query)  # years and "et al" aren't in a title or abstract
    words = [w for w in _words(query) if len(w) > 3] or _words(query)
    if not words:
        return 0
    phrase = " ".join(_words(query))
    title_words, all_words = " ".join(_words(title)), " ".join(_words(title + " " + summary))
    stems = lambda text: all(w[:5] in text for w in words)
    return 3 if f" {phrase} " in f" {title_words} " else 2 if stems(title_words) else 1 if stems(all_words) else 0


def sep(query: str, n: int = 2) -> list[dict]:
    page = _get("https://plato.stanford.edu/search/searcher.py?" + urllib.parse.urlencode({"query": query})).decode("utf-8", "replace")
    out, seen = [], set()
    for m in re.finditer(r'<div class="result_title"><a[^>]*href="[^"]*?entry=(/entries/[a-z0-9-]+/)[^"]*">(.*?)</a>.*?<div class="result_snippet">(.*?)</div>', page, re.S):
        path, title, snippet = m.group(1), _plain(m.group(2), 200), _plain(m.group(3))
        if path in seen or match(query, title, snippet) < EXPLAINER_MATCH:
            continue
        seen.add(path)
        out.append({
            "kind": "explainer", "source": SEP, "title": title, "authors": "", "year": None, "venue": SEP,
            "cited_by": None, "url": "https://plato.stanford.edu" + path, "summary": snippet,
        })
    return out[:n]


ATOM = {"a": "http://www.w3.org/2005/Atom"}


def libretexts(query: str, n: int = 2) -> list[dict]:
    out = []
    for lib in LIBRETEXTS:
        params = {"q": query, "offset": "0", "limit": str(n * 4), "format": "atom"}
        root = ET.fromstring(_get(f"https://{lib}.libretexts.org/@api/deki/site/opensearch?" + urllib.parse.urlencode(params)))
        for e in root.findall("a:entry", ATOM):
            link = e.find("a:link", ATOM)
            url = link.get("href", "") if link is not None else ""
            title, summary = _plain(e.findtext("a:title", "", ATOM), 200), _plain(e.findtext("a:content", "", ATOM))
            parts = urllib.parse.unquote(urllib.parse.urlsplit(url).path).strip("/").split("/")
            # A chapter in a book: Bookshelves/<subject>/<book>/<chapter>/... or Courses/<course>/<chapter>/...
            if (not url.startswith("https://") or len(parts) < 4 or re.search(r"\.[a-z0-9]{2,4}$", parts[-1], re.I)
                    or match(query, title, summary) < EXPLAINER_MATCH):  # a chapter page, not an image or file
                continue
            book = re.sub(r"_", " ", parts[2] if parts[0] == "Bookshelves" else parts[1])
            out.append({
                "kind": "explainer", "source": "LibreTexts", "title": title, "authors": "", "year": None,
                "venue": f"{book} (LibreTexts)", "cited_by": None, "url": url, "summary": summary,
            })
    return out[:n]


PAPER_QUERY = re.compile(r'\b10\.\d{4,9}/|arxiv|\b\d{4}\.\d{4,5}\b|\bet al\b|\b(?:1[5-9]|20)\d{2}\b|"', re.I)


JEV_TIMEOUT = 3  # seconds: search is interactive, so a slow answer falls back to the title match
OPENING = 1500  # characters of a result's own text Jev reads when it has no abstract
RECOMMEND_AT = 2.0  # Jev's relevance runs 0 to 4; 2 is "related", 3 out of 5 on a learner's scale
RELEVANCE = ["Unrelated to what was searched for",
             "Barely related: mentions it in passing",
             "Related: covers it, but it isn't the main subject",
             "Strongly related: mainly about it",
             "Exactly what was searched for, and would teach it well"]
ROLES = {"overview": "A general introduction or encyclopedia overview",
         "explainer": "An in-depth explanation, such as a textbook chapter or a philosophy encyclopedia entry",
         "review": "A review or survey that explains a field or a body of research",
         "study": "A primary study reporting its own research or result",
         "off_topic": "Not about what was searched for, or not credible scholarship"}


def judge(query: str, results: list[dict], openings: dict) -> dict:
    """Jev's relevance (0 to 4) and role for each result, by id(result); empty when Jev isn't there or fails."""
    if not results or not jev.available():
        return {}
    state = {"search": query, "results": [{"n": i, "title": r["title"], "from": r["source"],
                                           "text": (r.get("summary") or openings.get(id(r), ""))[:2 * OPENING]}
                                          for i, r in enumerate(results, 1)]}
    questions = {}
    for i in range(1, len(results) + 1):
        questions[f"r{i}_relevance"] = {"type": "score", "criteria": RELEVANCE,
                                        "instructions": f"How well would result n={i} help someone learn about what was searched for?"}
        questions[f"r{i}_role"] = {"type": "choice", "criteria": ROLES,
                                   "instructions": f"What kind of source is result n={i}, for someone learning about what was searched for?"}
    try:
        answers = jev.ask(state, questions, JEV_TIMEOUT)
        judged = {id(r): (float(answers[f"r{i}_relevance"]["score"]), answers[f"r{i}_role"]["choice"]) for i, r in enumerate(results, 1)}
    except (jev.JevError, KeyError, TypeError, ValueError) as e:
        logs.report("search ranking", e)  # the error's type and where, never the search
        return {}
    for r in results:
        relevance, role = judged[id(r)]
        r["judged"] = {"relevance": round(relevance + 1, 2), "role": role}  # on the 1 to 5 scale; not shown to learners
    return judged


def query_kind(query: str) -> str:
    """"paper" when the search looks for a particular paper (a DOI, an arXiv id, a year, "et al", a quoted or
    long title), otherwise "concept": an idea to learn about."""
    return "paper" if PAPER_QUERY.search(query) or len(query.split()) >= 8 else "concept"


def arxiv(query: str, n: int = 3) -> list[dict]:
    if arxiv_id := ARXIV_ID.search(query):  # an arXiv id names one preprint: look it up
        params = {"id_list": arxiv_id.group(1), "max_results": "1"}
        return _arxiv_results(ET.fromstring(_get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params))))
    phrase = search_words(query).replace('"', "")
    # An idea as a phrase; a paper by its words, since a remembered title, year or name won't match exactly.
    words = [w for w in _words(phrase) if len(w) > 3 and not re.fullmatch(r"\d+", w)]
    if query_kind(query) == "paper" and words:
        search_query = " AND ".join(f"all:{w}" for w in words)
    else:
        search_query = f'ti:"{phrase}" OR abs:"{phrase}"'
    params = {"search_query": search_query, "max_results": str(n), "sortBy": "relevance"}
    return _arxiv_results(ET.fromstring(_get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params))))


def _arxiv_results(root) -> list[dict]:
    out = []
    for e in root.findall("a:entry", ATOM):
        link = (e.findtext("a:id", "", ATOM) or "").strip()
        if not link:
            continue
        out.append({
            "kind": "paper", "source": "arXiv", "title": _plain(e.findtext("a:title", "", ATOM), 300),
            "authors": _authors([a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM)]),
            "year": int((e.findtext("a:published", "", ATOM) or "0")[:4] or 0) or None, "venue": "arXiv preprint", "cited_by": None,
            "url": link.replace("http://", "https://"), "summary": _plain(e.findtext("a:summary", "", ATOM)),
        })
    return out


def wikipedia(query: str) -> list[dict]:
    params = {"action": "query", "list": "search", "srsearch": query, "srlimit": "1", "format": "json", "utf8": "1"}
    data = json.loads(_get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)))
    out = []
    for r in (data.get("query") or {}).get("search") or []:
        title = r.get("title", "")
        out.append({
            "kind": "overview", "source": "Wikipedia", "title": title, "authors": "Wikipedia contributors", "year": None,
            "venue": "Encyclopedia article", "cited_by": None,
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "summary": _plain(r.get("snippet", "")),
        })
    return out


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:80]


_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def clean(query: str) -> str:
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    if not query:
        raise SearchError("Type a topic to search for.")
    if len(query) > MAX_QUERY:
        raise SearchError(f"Keep the search under {MAX_QUERY} characters.")
    return query


def cached(query: str) -> dict | None:
    """A recent result for this search, so it can be shown at once."""
    with _cache_lock:
        hit = _cache.get(clean(query).lower())
        return json.loads(json.dumps(hit)) if hit and time.time() - hit["checked_at"] < CACHE_TTL else None


def search(query: str, on_progress=None) -> dict:
    """Returns {"results": [...], "unavailable": [source names that didn't answer]}.

    ``on_progress`` is called with a fresh snapshot each time a service answers or a result is checked:
    {"services": {name: "searching" | "done" | "failed"}, "found": {name: count}, "to_check": n,
    "checked": n, "readable": n}."""
    query = clean(query)
    key = query.lower()
    if hit := cached(query):
        return hit
    result = _search(query, on_progress)
    if not result["unavailable"]:
        with _cache_lock:
            _cache[key] = result
            while len(_cache) > 50:
                _cache.pop(next(iter(_cache)))
    return json.loads(json.dumps(result))


RECOMMEND = {  # how many of each kind to suggest as a starting set
    "concept": {"overview": 1, "explainer": 1, "paper": 1},
    "paper": {"paper": 2, "overview": 1},
}
REASONS = {"overview": "Accessible overview", "explainer": "Explains the idea in depth", "paper": "Relevant paper for deeper evidence"}


def _search(query: str, on_progress=None) -> dict:
    calls = {"Wikipedia": wikipedia, SEP: sep, "LibreTexts": libretexts, "OpenAlex": openalex, "Europe PMC": europepmc, "arXiv": arxiv}
    if DOI.search(query):  # an identifier names one work, so only the service that can look it up is asked
        calls = {"OpenAlex": openalex}
    elif ARXIV_ID.search(query):
        calls = {"arXiv": arxiv}
    state = {"services": {name: "searching" for name in calls}, "found": {}, "to_check": 0, "checked": 0, "readable": 0}
    lock = threading.Lock()

    def report(**changes):
        with lock:
            for k, v in changes.items():
                state[k] = state[k] + v if k in ("checked", "readable") else v
            snapshot = json.loads(json.dumps(state))
        if on_progress:
            on_progress(snapshot)

    report()
    found, unavailable = {}, []
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {pool.submit(fn, query): name for name, fn in calls.items()}
        for f in as_completed(futures):  # report each service as it answers, not in a fixed order
            name = futures[f]
            try:
                found[name] = f.result()
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, ET.ParseError):
                found[name], unavailable = [], unavailable + [name]
            report(services={**state["services"], name: "failed" if name in unavailable else "done"},
                   found={**state["found"], name: len(found[name])})
    unavailable = [name for name in calls if name in unavailable]  # in a fixed order, whatever answered first
    # One entry per work. A copy found by another service adds its links, Europe PMC's open full text first.
    results, seen = [], {}
    for name in calls:
        for r in found[name]:
            r.setdefault("source", name)
            # The same work from two services, not an encyclopedia article named after a paper.
            k = (r["kind"], _key(r["title"]))
            if not k[1]:
                continue
            r.pop("score", None)
            if k in seen:
                kept, extra = seen[k], r.get("urls") or [r["url"]]
                mine = kept.get("urls") or [kept["url"]]
                kept["urls"] = list(dict.fromkeys(extra + mine if r["source"] == "Europe PMC" else mine + extra))[:5]  # a build accepts at most five links per source
                continue
            seen[k] = r
            results.append(r)
    if not results and len(unavailable) == len(calls):
        raise SearchError("Couldn't reach any of the search services. Check your connection and try again.")
    report(to_check=len(results))

    openings = {}  # the start of each verified text, by id(result): what Jev reads for a result without an abstract

    def check(result):
        urls = result.get("urls") or [result["url"]]
        try:
            paper = ingest.first_readable(urls, timeout=CHECK_TIMEOUT, budget=CHECK_BUDGET)
        except ingest.IngestError as e:
            result.update(available=False, availability_error=str(e))
        else:
            # Open the verified copy, not a publisher link that may have returned 403.
            result.update(available=True, url=paper.url, urls=list(dict.fromkeys([paper.url] + urls))[:5])
            openings[id(result)] = paper.text[:OPENING]
        result["link"] = ingest.reader_link(result["url"])  # what the learner opens, which may differ from what Lemma reads
        report(checked=1, readable=int(result["available"]))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check, results))
    # Readable papers first, in rank order; unreadable ones only fill the places left, so the learner can
    # still open them and upload the PDF when little is readable. Preprints follow, then the rest by kind.
    # Within each group, the closer a title is to the search, the earlier; ties keep each service's own ranking.
    closeness = lambda r: -match(query, r["title"], r.get("summary", "") + " " + (r.get("authors") or ""))
    # When the search is for an idea, a paper whose title and abstract never mention it is dropped (one without
    # an abstract is kept). A search for a paper holds names and years that abstracts don't, so it keeps them all.
    mode = query_kind(query)
    if mode == "concept":
        results = [r for r in results if r["kind"] != "paper" or not r.get("summary") or closeness(r) < 0]
    # Jev, when this server has a TypeSafe key, judges how well each result would teach what was searched for;
    # that orders each group, with the title match breaking ties. Without it, the title match alone orders them.
    judged = judge(query, results, openings)
    rank = lambda r: (-judged.get(id(r), (0, ""))[0], closeness(r))
    indexed = [r for r in results if r["source"] in ("OpenAlex", "Europe PMC")]
    papers = sorted(indexed, key=lambda r: (not r["available"], *rank(r)))[:PAPERS]
    papers += sorted((r for r in results if r["source"] == "arXiv"), key=rank)
    if mode == "paper":  # one particular paper: the closest match leads, whichever service found it
        papers.sort(key=lambda r: (not r["available"], *rank(r)))
    by_kind = {kind: sorted((r for r in results if r["kind"] == kind), key=rank) for kind in ("overview", "explainer")}
    order = ["overview", "explainer", "paper"] if mode == "concept" else ["paper", "overview", "explainer"]
    results = [r for kind in order for r in (papers if kind == "paper" else by_kind[kind])]
    # A small, complementary starting set from sources that passed actual ingestion.
    left = dict(RECOMMEND[mode])
    for result in results:
        relevance, role = judged.get(id(result), (RECOMMEND_AT, ""))
        suits = relevance >= RECOMMEND_AT and role != "off_topic"  # Jev's judgement, when there is one
        result["recommended"] = bool(result["available"] and suits and left.get(result["kind"]))
        if result["recommended"]:
            left[result["kind"]] -= 1
            result["recommendation"] = REASONS[result["kind"]]
    return {"query": query, "kind": mode, "results": results, "unavailable": unavailable, "checked_at": time.time()}
