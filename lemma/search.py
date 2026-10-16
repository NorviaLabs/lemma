"""Finding something to learn from: search a topic across open scholarly indexes.

Search words go to OpenAlex, arXiv and Wikipedia; source sites are then contacted to verify
readable full text. OpenAlex returns open-access papers ranked by relevance and citations,
arXiv returns preprints, and Wikipedia returns one overview article. None needs an account
or key. Only verified readable sources are recommended.
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
from concurrent.futures import ThreadPoolExecutor

from . import ingest
from .ingest import USER_AGENT

TIMEOUT = 12
MAX_QUERY = 200
CHECK_TIMEOUT = 8
CACHE_TTL = 300
SOURCES = ("OpenAlex", "arXiv", "Wikipedia")


class SearchError(Exception):
    pass


MAX_WAIT = 15  # seconds we'll wait once when a service asks us to slow down


def _get(url: str, retry: bool = True) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/atom+xml;q=0.9"})
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


def openalex(query: str, n: int = 6) -> list[dict]:
    params = {
        "search": query,
        "filter": "is_oa:true,type:article|preprint|review",
        "per-page": "25",
        "select": "id,display_name,publication_year,authorships,primary_location,best_oa_location,locations,cited_by_count,abstract_inverted_index,relevance_score",
    }
    data = json.loads(_get("https://api.openalex.org/works?" + urllib.parse.urlencode(params)))
    out = []
    for w in data.get("results") or []:
        # Every open copy, best first: if one can't be read (a scan, a blocked download), Lemma tries the next.
        locs = [w.get("best_oa_location") or {}] + [l for l in w.get("locations") or [] if l.get("is_oa")]
        urls = [u for l in locs for u in (l.get("pdf_url"), l.get("landing_page_url"))
                if u and re.match(r"^https?://[^\s<>\"]+$", u) and "orcid.org" not in u]
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
            # Relevance first, nudged up by how much the field has used the paper.
            "score": float(w.get("relevance_score") or 0) * math.log10(cites + 10),
        })
    out.sort(key=lambda r: -r["score"])
    return out[:n]


ATOM = {"a": "http://www.w3.org/2005/Atom"}


def arxiv(query: str, n: int = 3) -> list[dict]:
    phrase = query.replace('"', "")
    params = {"search_query": f'ti:"{phrase}" OR abs:"{phrase}"', "max_results": str(n), "sortBy": "relevance"}
    root = ET.fromstring(_get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)))
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


def search(query: str) -> dict:
    """Returns {"results": [...], "unavailable": [source names that didn't answer]}."""
    query = re.sub(r"\s+", " ", str(query or "")).strip()
    if not query:
        raise SearchError("Type a topic to search for.")
    if len(query) > MAX_QUERY:
        raise SearchError(f"Keep the search under {MAX_QUERY} characters.")
    key = query.lower()
    with _cache_lock:
        if key in _cache and time.time() - _cache[key]["checked_at"] < CACHE_TTL:
            return json.loads(json.dumps(_cache[key]))
    result = _search(query)
    if not result["unavailable"]:
        with _cache_lock:
            _cache[key] = result
            while len(_cache) > 50:
                _cache.pop(next(iter(_cache)))
    return json.loads(json.dumps(result))


def _search(query: str) -> dict:
    calls = {"OpenAlex": openalex, "arXiv": arxiv, "Wikipedia": wikipedia}
    found, unavailable = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(fn, query) for name, fn in calls.items()}
        for name, f in futures.items():
            try:
                found[name] = f.result()
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, ET.ParseError):
                found[name], unavailable = [], unavailable + [name]
    # An overview first for a newcomer, then the most-used papers, then preprints not already listed.
    results, seen = [], set()
    for r in found["Wikipedia"] + found["OpenAlex"] + found["arXiv"]:
        k = _key(r["title"])
        if k and k not in seen:
            seen.add(k)
            r.pop("score", None)
            results.append(r)
    if not results and len(unavailable) == len(calls):
        raise SearchError("Couldn't reach any of the search services. Check your connection and try again.")
    def check(result):
        urls = result.get("urls") or [result["url"]]
        try:
            paper = ingest.first_readable(urls, timeout=CHECK_TIMEOUT)
        except ingest.IngestError as e:
            result.update(available=False, availability_error=str(e))
        else:
            # Open the verified copy, not a publisher link that may have returned 403.
            result.update(available=True, url=paper.url, urls=list(dict.fromkeys([paper.url] + urls)))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check, results))
    # A small, complementary starting set from sources that passed actual ingestion.
    papers = 0
    overview = False
    for result in results:
        recommended = result["available"] and ((result["kind"] == "overview" and not overview) or (result["kind"] == "paper" and papers < 2))
        result["recommended"] = recommended
        if recommended:
            overview |= result["kind"] == "overview"
            papers += result["kind"] == "paper"
            result["recommendation"] = "Accessible overview" if result["kind"] == "overview" else "Relevant paper for deeper evidence"
    return {"query": query, "results": results, "unavailable": unavailable, "checked_at": time.time()}
