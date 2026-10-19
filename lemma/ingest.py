"""Turn a link, a PDF or a saved web page into plain text."""

from __future__ import annotations

import html
import http.client
import io
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser

MAX_BYTES = 40 * 1024 * 1024  # a PDF
MAX_PAGE_BYTES = 10 * 1024 * 1024  # anything else: parsing HTML takes many times its size in memory
MAX_CHARS = 2_000_000  # text kept from any source, far more than a lesson uses
MAX_PDF_PAGES = 500
FETCH_DEADLINE = 60  # seconds for a whole download, however slowly the site sends it
PDF_DEADLINE = 60  # seconds to read one PDF's text; a small file can expand to hours of work
READER_WAIT = 30  # seconds to wait for a free PDF reader before giving up
PDF_MEMORY = 512 * 1024 * 1024  # address space for the PDF reader; a small file can expand to gigabytes
MAX_DOWNLOADS = 4  # links read at once across the whole server, from searches, builds and pasted links
USER_AGENT = "Lemma/1.0 (local paper reader)"
FULL_TEXT = 4000  # Shorter pages are usually abstracts, not usable full text.
# Reading a large PDF can take hundreds of MB, so only a couple are read at once; the rest wait their turn.
_PDF_READERS = threading.BoundedSemaphore(2)
_DOWNLOADS = threading.BoundedSemaphore(MAX_DOWNLOADS)
BUSY = "OpenLemma is busy reading other sources. Try again in a minute."
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
        raise IngestError("The sites hosting this one were too slow to answer. Try again later, or save the PDF and add it as a file.")
    if short or not first:
        raise IngestError("OpenLemma could only find a short summary of this one, not the full text. Try another result, or save the PDF and add it as a file.")
    raise first


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_CHARS]


def from_pdf(data: bytes, url: str = "") -> Paper:
    if not _PDF_READERS.acquire(timeout=READER_WAIT):
        raise IngestError(BUSY)
    try:
        found = _read_pdf_in_child(data)
    finally:
        _PDF_READERS.release()
    text = _clean(found["text"])
    if len(text) < 500:
        raise IngestError("This PDF has almost no extractable text. It may be a scanned image; try a version with selectable text.")
    title = found["title"].strip()
    if not title or len(title) < 6 or title.lower().startswith(("microsoft", "untitled")):
        title = _guess_title(text)
    return Paper(text=text, title=title, kind="pdf", url=url, pages=found["pages"])


def _read_pdf_in_child(data: bytes) -> dict:
    """Read the PDF in a separate process that is killed at the deadline, since pypdf can't be interrupted."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = "import sys; sys.path.insert(0, sys.argv[1]); from lemma.ingest import _pdf_child; _pdf_child(*map(int, sys.argv[2:5]))"
    try:  # -I: the working directory and PYTHON* variables can't change what the child imports
        done = subprocess.run([sys.executable, "-I", "-c", code, root, str(MAX_PDF_PAGES), str(MAX_CHARS), str(PDF_MEMORY)],
                              input=data, capture_output=True, timeout=PDF_DEADLINE, env=_child_env())
    except subprocess.TimeoutExpired:
        raise IngestError("This PDF took too long to read. Try another copy of the source, or its web page.") from None
    try:
        found = json.loads(done.stdout)
    except ValueError:
        raise IngestError("Couldn't read this PDF.") from None
    if "error" in found:
        raise IngestError(found["error"])
    return found


def _child_env() -> dict:
    """The PDF reader's environment: enough to run Python, and none of the server's keys or secrets."""
    return {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")}


def _pdf_child(max_pages: int, max_chars: int, max_memory: int = 0) -> None:
    """The child process: a PDF on stdin, its text, title and page count as JSON on stdout."""
    if max_memory:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (max_memory, max_memory))
        except (ImportError, ValueError, OSError):  # not every platform enforces it (macOS doesn't)
            pass
    try:
        found = _read_pdf(sys.stdin.buffer.read(), max_pages, max_chars)
    except IngestError as e:
        found = {"error": str(e)}
    except MemoryError:
        found = {"error": "This PDF is too complex to read. Try another copy of the source, or its web page."}
    sys.stdout.write(json.dumps(found))


def _read_pdf(data: bytes, max_pages: int, max_chars: int) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise IngestError("PDF support needs the 'pypdf' package") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")  # PasswordType.NOT_DECRYPTED (0) when it needs a password
            except Exception:
                opened = False
            if not opened:
                raise IngestError("This PDF is password-protected.")
        pages, size = [], 0
        for page in reader.pages:
            if len(pages) == max_pages or size >= max_chars:
                break
            pages.append(page.extract_text() or "")
            size += len(pages[-1])
    except IngestError:
        raise
    except Exception as e:
        raise IngestError(f"Couldn't read this PDF ({e.__class__.__name__}).") from None
    title = ""
    try:
        meta = reader.metadata
        title = (meta.title or "") if meta else ""
    except Exception:
        pass
    return {"text": "\n\n".join(pages)[:max_chars], "title": str(title), "pages": len(pages)}


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
        raise IngestError("This page has very little text. If the source is behind a login or loads with JavaScript, save the PDF and add it as a file instead.")
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
        raise IngestError("This text is too short to teach from.")
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


# One message for unknown and private hosts, so a link can't be used to probe which internal names exist.
NOT_PUBLIC = "OpenLemma couldn't reach that address. It only fetches public web addresses, so check the link or upload the file instead."
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether `ip` is a public unicast address. An IPv6 address that carries an IPv4 one is judged by the IPv4 one."""
    if ip.version == 6:
        if ip in _IPV4_COMPATIBLE:
            return False
        inner = ip.ipv4_mapped or ip.sixtofour or (ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF) if ip in _NAT64 else None)
        if inner:
            ip = inner
    return ip.is_global and not ip.is_multicast


def _public_addresses(host: str, port: int) -> list[tuple]:
    """The addresses `host` resolves to, or IngestError if any of them is private, loopback or reserved."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise IngestError(NOT_PUBLIC) from None
    if not all(_is_public(ipaddress.ip_address(info[4][0].split("%")[0])) for info in infos):
        raise IngestError(NOT_PUBLIC)
    return infos


class _Deadline:
    """Cuts every connection a fetch opens once its time is up, wherever the fetch is blocked: connecting,
    reading headers or reading the body. A per-read timeout alone lets a site send one byte at a time forever."""

    current = threading.local()

    def __init__(self, seconds: float):
        self.expired = False
        self._socks: list[socket.socket] = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True

    def __enter__(self):
        _Deadline.current.value = self
        self._timer.start()
        return self

    def __exit__(self, *exc):
        self._timer.cancel()
        _Deadline.current.value = None
        with self._lock:
            for s in self._socks:
                s.close()

    def watch(self, sock: socket.socket) -> None:
        with self._lock:
            self._socks.append(sock.dup())  # TLS takes over the original; shutting down a duplicate still cuts the connection
            if self.expired:
                self._cut(self._socks[-1])

    def _expire(self) -> None:
        with self._lock:
            self.expired = True
            for s in self._socks:
                self._cut(s)

    @staticmethod
    def _cut(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


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
            deadline = getattr(_Deadline.current, "value", None)
            if deadline:
                deadline.watch(sock)
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
            raise IngestError("That link redirects somewhere OpenLemma can't follow.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# No proxies from the environment, so every connection goes through _connect_public.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PublicHandler, _Redirects)


def from_url(url: str, timeout: float | None = None) -> Paper:
    """Download and read a link. `timeout` caps the seconds for the whole download."""
    url = _normalise_url(url)
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise IngestError("Only http and https links are supported.")
    timeout = min(timeout or FETCH_DEADLINE, FETCH_DEADLINE)
    if not _DOWNLOADS.acquire(timeout=min(timeout, READER_WAIT)):
        raise IngestError(BUSY)
    try:  # held through reading the text too, since parsing a page takes many times its size in memory
        return _download_and_read(url, timeout)
    finally:
        _DOWNLOADS.release()


def _download_and_read(url: str, timeout: float) -> Paper:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,application/xml;q=0.8,*/*;q=0.5"})
    with _Deadline(timeout) as deadline:
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                final = resp.geturl()
                ctype = resp.headers.get_content_type()
                data = _read_body(resp, pdf=ctype == "application/pdf" or final.lower().endswith(".pdf"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise IngestError(f"This site blocks automatic downloads or needs a login. Open it in your browser, save the PDF, and add it as a file. (Site answered {e.code}.)") from None
            raise IngestError(f"This link didn't open. Check it, or open it in your browser, save the PDF, and add it as a file. (Site answered {e.code}.)") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            if deadline.expired or isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                raise IngestError("The site took too long to respond.") from None
            raise IngestError(f"Couldn't reach that link ({getattr(e, 'reason', e)}).") from None
        if deadline.expired:  # a cut connection can look like the end of the file
            raise IngestError("The site took too long to respond.")
    return from_bytes(data, filename=final, content_type=ctype, url=url)


def _read_body(resp, pdf: bool) -> bytes:
    """The response body, refused as soon as it passes the size limit rather than after downloading it all."""
    limit = MAX_BYTES if pdf else MAX_PAGE_BYTES
    chunks, size = [], 0
    while chunk := resp.read1(1 << 16):
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            if limit < MAX_BYTES and b"".join(chunks[:5])[:5] == b"%PDF-":  # a PDF the site didn't label as one
                limit = MAX_BYTES
                continue
            what = "file" if limit == MAX_BYTES else "page"
            raise IngestError(f"That {what} is larger than {limit // (1024 * 1024)} MB. Save the source's PDF and add it as a file instead.")
    return b"".join(chunks)


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
        raise IngestError("OpenLemma reads PDFs, web pages and plain text files.")
    return paper
