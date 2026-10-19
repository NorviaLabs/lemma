"""Reading links, files and articles: what a learner is told when a source can't be read, and what Lemma requests.

Every link is served by a loopback server that the tests let through the public-address guard as "pub.test";
nothing leaves this computer.
"""

from __future__ import annotations

import io
import socket
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from lemma import ingest
from test_ingest_hardening import make_pdf

PARAGRAPH = "Plants turn light, water and carbon dioxide into sugar and oxygen, and they store the sugar for later. " * 3

JATS = f"""<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
 <front><article-meta><title-group><article-title>Light and   the leaf</article-title></title-group>
  <abstract><p>{PARAGRAPH}</p></abstract></article-meta></front>
 <body><sec><title>Methods</title><p>{PARAGRAPH}</p><fig><caption><p>A leaf under a lamp.</p></caption></fig></sec></body>
 <back><ref-list><ref><article-title>A cited paper that is not part of the text</article-title></ref></ref-list></back>
</article>""".encode()


def page(text):
    return f"<html><head><title>Plants</title></head><body><p>{text}</p></body></html>".encode()


class Site(BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        status, headers, body = self.routes[self.path]
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Links(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://pub.test:{cls.port}"
        unlabelled = make_pdf(pages=1, lines_per_page=40, padding=3000)
        Site.routes = {
            "/gone": (404, {"Content-Type": "text/html"}, b"<p>Not here</p>"),
            "/to-ftp": (302, {"Location": "ftp://files.example.org/paper.pdf"}, b""),
            "/to-file": (302, {"Location": "file:///etc/passwd"}, b""),
            "/article": (200, {"Content-Type": "application/xml"}, JATS),
            "/download": (200, {"Content-Type": "application/octet-stream"}, unlabelled),
            "/data.bin": (200, {"Content-Type": "application/octet-stream"}, b"\x00\x01\x02" * 400),
            "/page": (200, {"Content-Type": "text/html"}, page(PARAGRAPH * 3)),
        }

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.addresses = None
        orig = ingest._public_addresses

        def pretend_public(host, port):  # "pub.test" stands for a public site served by this test
            if host == "pub.test":
                return self.addresses or socket.getaddrinfo("127.0.0.1", port, type=socket.SOCK_STREAM)
            return orig(host, port)

        p = patch.object(ingest, "_public_addresses", pretend_public)
        p.start()
        self.addCleanup(p.stop)

    def test_a_site_that_refuses_says_so_and_suggests_uploading(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_url(self.base + "/gone")
        self.assertEqual(str(e.exception), "This link didn't open. Check it, or open it in your browser, save the PDF, and add it as a file. (Site answered 404.)")

    def test_redirects_only_to_web_addresses_are_followed(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_url(self.base + "/to-ftp")
        self.assertEqual(str(e.exception), "That link redirects somewhere OpenLemma can't follow.")
        with self.assertRaises(ingest.IngestError) as e:  # urllib itself refuses file: before Lemma is asked
            ingest.from_url(self.base + "/to-file")
        self.assertNotIn("root:", str(e.exception))

    def test_a_journal_article_in_xml_keeps_its_text_and_drops_its_references(self):
        paper = ingest.from_url(self.base + "/article")
        self.assertEqual((paper.kind, paper.title), ("xml", "Light and the leaf"))
        self.assertTrue(paper.text.startswith("Light and the leaf\n\nAbstract\n\nPlants turn light"), paper.text[:80])
        self.assertIn("Methods", paper.text)
        self.assertIn("A leaf under a lamp.", paper.text)
        self.assertNotIn("A cited paper", paper.text)

    def test_a_pdf_the_site_does_not_label_may_pass_the_page_limit(self):
        with patch.object(ingest, "MAX_PAGE_BYTES", 2000):
            paper = ingest.from_url(self.base + "/download")
        self.assertEqual((paper.kind, paper.pages), ("pdf", 1))

    def test_a_file_that_is_not_a_paper_is_refused(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_url(self.base + "/data.bin")
        self.assertEqual(str(e.exception), "OpenLemma reads PDFs, web pages and plain text files.")

    def test_a_closed_port_reads_as_unreachable(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_url(f"http://pub.test:{closed_port()}/page")
        self.assertTrue(str(e.exception).startswith("Couldn't reach that link ("), e.exception)

    def test_each_checked_address_is_tried_in_turn(self):
        dead = socket.getaddrinfo("127.0.0.1", closed_port(), type=socket.SOCK_STREAM)
        live = socket.getaddrinfo("127.0.0.1", self.port, type=socket.SOCK_STREAM)
        self.addresses = dead + live
        self.assertEqual(ingest.from_url(self.base + "/page").title, "Plants")

    def test_https_links_need_a_working_tls_server(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_url(f"https://pub.test:{self.port}/page")  # this site speaks plain HTTP only
        self.assertTrue(str(e.exception).startswith("Couldn't reach that link ("), e.exception)

    def test_a_timeout_while_connecting_reads_as_slow(self):
        with patch.object(ingest, "_connect_public", side_effect=TimeoutError("timed out")):
            with self.assertRaises(ingest.IngestError) as e:
                ingest.from_url(self.base + "/page")
        self.assertEqual(str(e.exception), "The site took too long to respond.")


class RequestedAddress(unittest.TestCase):
    """The address Lemma actually asks for, seen by replacing the opener that would send it."""

    def requested(self, link):
        sent = []

        def opener(req, timeout=None):
            sent.append(req.full_url)
            raise urllib.error.URLError("stopped by the test")

        with patch.object(ingest, "_OPENER", SimpleNamespace(open=opener)), self.assertRaises(ingest.IngestError):
            ingest.from_url(link)
        return sent[0]

    def test_arxiv_abstract_pages_are_read_as_their_pdf(self):
        self.assertEqual(self.requested("https://arxiv.org/abs/2101.00001v2"), "https://arxiv.org/pdf/2101.00001v2")
        self.assertEqual(self.requested("https://export.arxiv.org/html/2101.00001/"), "https://arxiv.org/pdf/2101.00001")
        self.assertEqual(self.requested("https://arxiv.org/list/cs.AI/recent"), "https://arxiv.org/list/cs.AI/recent")

    def test_a_link_without_a_scheme_is_read_over_https(self):
        self.assertEqual(self.requested("  example.org/paper  "), "https://example.org/paper")


class Files(unittest.TestCase):
    def test_a_corrupt_pdf_is_refused_plainly(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_bytes(b"%PDF-1.4\n" + b"not really a pdf " * 50)
        self.assertRegex(str(e.exception), r"^Couldn't read this PDF \(\w+\)\.$")

    def test_a_pdf_reader_that_dies_is_refused_plainly(self):
        died = SimpleNamespace(stdout=b"", stderr=b"Killed", returncode=-9)
        with patch.object(ingest.subprocess, "run", return_value=died):
            with self.assertRaises(ingest.IngestError) as e:
                ingest.from_bytes(make_pdf(1, 30))
        self.assertEqual(str(e.exception), "Couldn't read this PDF.")

    def test_web_pages_keep_their_article_text_and_title(self):
        html = (b"<html><head><meta charset='x-made-up'><title>Site name</title>"
                b"<meta property='og:title' content='Social title'><meta name='citation_title' content='The Paper Title'></head>"
                b"<body><nav>Home | About</nav><script>var x = 1;</script><header>Menu</header>"
                b"<article><h1>Heading</h1><p>" + PARAGRAPH.encode() + b"</p><p>" + PARAGRAPH.encode() + b"</p></article>"
                b"<footer>Copyright</footer></body></html>")
        paper = ingest.from_bytes(html, content_type="text/html")
        self.assertEqual(paper.title, "The Paper Title")
        for chrome in ("Home | About", "var x", "Menu", "Copyright"):
            self.assertNotIn(chrome, paper.text)
        self.assertTrue(paper.text.startswith("Heading\n\nPlants turn light"), paper.text[:40])
        og_only = html.replace(b"<meta name='citation_title' content='The Paper Title'>", b"")
        self.assertEqual(ingest.from_bytes(og_only, filename="page.html").title, "Social title")

    def test_short_pages_texts_and_articles_are_refused(self):
        cases = [(page("Sign in to read this article."), "text/html", "very little text"),
                 (b"Too short to be a paper.", "text/plain", "too short to teach from"),
                 (b"<article><p>Only an abstract.</p></article>", "application/xml", "almost no text"),
                 (b"<article><p>Unclosed", "application/xml", "Couldn't read this article's XML.")]
        for data, ctype, message in cases:
            with self.subTest(ctype=ctype, message=message), self.assertRaises(ingest.IngestError) as e:
                ingest.from_bytes(data, content_type=ctype)
            self.assertIn(message, str(e.exception))


if __name__ == "__main__":
    unittest.main()
