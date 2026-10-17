"""Turn a link, a PDF or a saved web page into plain text."""

from __future__ import annotations

import html
import http.client
import io
import ipaddress
import logging
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser

MAX_BYTES = 40 * 1024 * 1024
USER_AGENT = "Lemma/1.0 (local paper reader)"
FULL_TEXT = 4000  # Shorter pages are usually abstracts, not usable full text.
# Reading a large PDF can take hundreds of MB, so only a couple are read at once; the rest wait their turn.
_PDF_READERS = threading.BoundedSemaphore(2)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # its font warnings would fill the server's error log


class IngestError(Exception):
    pass


EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/"


def europe_pmc_full_text(pmcid: str) -> str:
    """Europe PMC's open-access full text: the readable copy of a PMC article, which PMC's own pages hide
    behind a challenge for anything that isn't a browser."""
    return f"{EUROPE_PMC}{pmcid}/fullTextXML"


def reader_link(url: str) -> str:
    """The page a person opens for a link Lemma reads: Europe PMC's article page rather than its raw XML."""
    m = re.fullmatch(re.escape(EUROPE_PMC) + r"(PMC\d+)/fullTextXML", url or "")
    return f"https://europepmc.org/article/PMC/{m.group(1)}" if m else url


@dataclass
class Paper:
    text: str
    title: str
    kind: str  # "pdf" | "html" | "text" | "xml"
    url: str = ""
    pages: int = 0


def first_readable(urls: list[str], timeout: float | None = None, budget: float | None = None) -> Paper:
    """Use the same full-text check for recommendations and lesson ingestion.

    ``budget`` caps the seconds spent on all the links together, so a few slow hosts can't hold up a search."""
    first, short, slow = None, False, False
    deadline = time.monotonic() + budget if budget else None
    for url in urls:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left < 1:
                slow = True
                break
            timeout = min(timeout or left, left)
        try:
            paper = from_url(url, timeout=timeout) if timeout is not None else from_url(url)
        except IngestError as e:
            first = first or e
            continue
        if len(paper.text) >= FULL_TEXT:
            return paper
        short = True
    if slow and not short:
        raise IngestError("The sites hosting this one were too slow to answer. Try again later, or download it and upload the PDF.")
    if short or not first:
        raise IngestError("Lemma could only find a short summary of this one, not the full text. Try another result, or download it and upload the PDF.")
    raise first


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def from_pdf(data: bytes, url: str = "") -> Paper:
    with _PDF_READERS:
        return _read_pdf(data, url)


def _read_pdf(data: bytes, url: str) -> Paper:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise IngestError("PDF support needs the 'pypdf' package") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise IngestError("This PDF is password-protected.") from None
        pages = [(p.extract_text() or "") for p in reader.pages]
    except IngestError:
        raise
    except Exception as e:
        raise IngestError(f"Couldn't read this PDF ({e.__class__.__name__}).") from None
    text = _clean("\n\n".join(pages))
    if len(text) < 500:
        raise IngestError("This PDF has almost no extractable text. It may be a scanned image; try a version with selectable text.")
    title = ""
    try:
        meta = reader.metadata
        title = (meta.title or "").strip() if meta else ""
    except Exception:
        pass
    if not title or len(title) < 6 or title.lower().startswith(("microsoft", "untitled")):
        title = _guess_title(text)
    return Paper(text=text, title=title, kind="pdf", url=url, pages=len(pages))


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button", "template"}
    BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "blockquote", "figcaption", "pre", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self.meta_title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and a.get("name", "").lower() in ("citation_title", "dc.title") and a.get("content"):
            self.meta_title = a["content"]
        elif tag == "meta" and a.get("property", "").lower() == "og:title" and a.get("content") and not self.meta_title:
            self.meta_title = a["content"]
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def from_html(data: bytes | str, url: str = "") -> Paper:
    if isinstance(data, bytes):
        m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', data[:4096])
        enc = m.group(1).decode() if m else "utf-8"
        try:
            data = data.decode(enc, errors="replace")
        except LookupError:
            data = data.decode("utf-8", errors="replace")
    p = _TextExtractor()
    p.feed(data)
    text = _clean(html.unescape("".join(p.parts)))
    if len(text) < 500:
        raise IngestError("This page has very little text. If the paper is behind a login or loads with JavaScript, download the PDF and upload it instead.")
    title = (p.meta_title or p.title or "").strip() or _guess_title(text)
    return Paper(text=text, title=re.sub(r"\s+", " ", title), kind="html", url=url)


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def from_jats(data: bytes | str, url: str = "") -> Paper:
    """A journal article in JATS XML, the format of Europe PMC's open-access full texts: the title, the
    abstract and the body's headings and paragraphs, without the reference list."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise IngestError("Couldn't read this article's XML.") from None
    found = {}  # the first of each: the article's own title comes before the titles it cites
    for e in root.iter():
        if _local(e.tag) in ("article-title", "abstract", "body"):
            found.setdefault(_local(e.tag), e)
    flat = lambda e: re.sub(r"\s+", " ", "".join(e.itertext())).strip()
    title = flat(found["article-title"]) if "article-title" in found else ""
    parts = [title] if title else []
    for part, heading in (("abstract", "Abstract"), ("body", "")):
        if part not in found:
            continue
        if heading:
            parts.append(heading)
        for e in found[part].iter():
            if _local(e.tag) in ("title", "p", "caption") and flat(e):
                parts.append(flat(e))
    text = _clean("\n\n".join(parts))
    if len(text) < 500:
        raise IngestError("This article's XML has almost no text.")
    return Paper(text=text, title=title or _guess_title(text), kind="xml", url=url)


def from_text(data: bytes | str, url: str = "") -> Paper:
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    text = _clean(data)
    if len(text) < 500:
        raise IngestError("This text is too short to be a paper.")
    return Paper(text=text, title=_guess_title(text), kind="text", url=url)


def _guess_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if 12 <= len(line) <= 200 and not re.match(r"^(arxiv|doi|page|\d)", line, re.I):
            return line
    return "Untitled paper"


def _normalise_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.endswith("arxiv.org"):
        m = re.match(r"^/(abs|html)/(.+?)(v\d+)?/?$", parts.path)
        if m:
            return f"https://arxiv.org/pdf/{m.group(2)}{m.group(3) or ''}"
    return url


def _public_addresses(host: str, port: int) -> list[tuple]:
    """The addresses `host` resolves to, or IngestError if any of them is private, loopback or reserved."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise IngestError(f"Couldn't find the site {host!r}. Check the link and your connection.") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise IngestError("Lemma only fetches public web addresses. Upload the file instead.")
    return infos


def _connect_public(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """Like socket.create_connection, but checks the addresses as it connects and uses only those it checked,
    so neither a redirect nor a second DNS answer can point a fetch at this server's own network."""
    host, port = address
    err = None
    for family, kind, proto, _, sockaddr in _public_addresses(host, port):
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            sock.close()
            err = e
    raise err or OSError(f"Couldn't connect to {host}")


class _PublicHTTP(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_public


class _PublicHTTPS(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_public  # TLS still checks the certificate against the host name


class _PublicHandler(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTP, req)

    def https_open(self, req):
        return self.do_open(_PublicHTTPS, req, context=ssl.create_default_context())


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme not in ("http", "https"):
            raise IngestError("That link redirects somewhere Lemma can't follow.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# No proxies from the environment, so every connection goes through _connect_public.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PublicHandler, _Redirects)


def from_url(url: str, timeout: float = 30) -> Paper:
    url = _normalise_url(url)
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise IngestError("Only http and https links are supported.")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,application/xml;q=0.8,*/*;q=0.5"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            final = resp.geturl()
            ctype = resp.headers.get_content_type()
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise IngestError(f"The site answered {e.code} {e.reason}: it blocks automatic downloads or needs a login. Open it in your browser, download the PDF and upload it.") from None
    except urllib.error.URLError as e:
        raise IngestError(f"Couldn't reach that link ({e.reason}).") from None
    except TimeoutError:
        raise IngestError("The site took too long to respond.") from None
    if len(data) > MAX_BYTES:
        raise IngestError("That file is larger than 40 MB.")
    return from_bytes(data, filename=final, content_type=ctype, url=url)


def from_bytes(data: bytes, filename: str = "", content_type: str = "", url: str = "") -> Paper:
    name = filename.lower()
    if data[:5] == b"%PDF-" or content_type == "application/pdf" or name.endswith(".pdf"):
        paper = from_pdf(data, url)
    elif content_type in ("application/xml", "text/xml") and b"<article" in data[:4096]:
        paper = from_jats(data, url)
    elif content_type in ("text/html", "application/xhtml+xml") or name.endswith((".html", ".htm", ".xhtml")) or b"<html" in data[:2048].lower():
        paper = from_html(data, url)
    elif content_type.startswith("text/") or name.endswith((".txt", ".md")):
        paper = from_text(data, url)
    else:
        raise IngestError("Lemma reads PDFs, web pages and plain text files.")
    return paper
