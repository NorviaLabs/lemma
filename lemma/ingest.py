"""Turn a link, a PDF or a saved web page into plain text."""

from __future__ import annotations

import html
import http.client
import io
import ipaddress
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

MAX_BYTES = 40 * 1024 * 1024
MAX_CHARS = 1_500_000  # roughly 400k tokens; longer documents are refused, never truncated
USER_AGENT = "Lemma/1.0 (local paper reader)"


class IngestError(Exception):
    pass


@dataclass
class Paper:
    text: str
    title: str
    kind: str  # "pdf" | "html" | "text"
    url: str = ""
    pages: int = 0


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def from_pdf(data: bytes, url: str = "") -> Paper:
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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            final = resp.geturl()
            ctype = resp.headers.get_content_type()
            data = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise IngestError(f"The site answered {e.code} {e.reason}. If the paper needs a login, download it and upload the PDF.") from None
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
    elif content_type in ("text/html", "application/xhtml+xml") or name.endswith((".html", ".htm", ".xhtml")) or b"<html" in data[:2048].lower():
        paper = from_html(data, url)
    elif content_type.startswith("text/") or name.endswith((".txt", ".md")):
        paper = from_text(data, url)
    else:
        raise IngestError("Lemma reads PDFs, web pages and plain text files.")
    if len(paper.text) > MAX_CHARS:
        raise IngestError(f"This document is very long ({len(paper.text):,} characters). Lemma works with a single paper; try uploading just the paper rather than a book or a collection.")
    return paper
