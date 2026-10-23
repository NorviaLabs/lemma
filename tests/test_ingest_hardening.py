"""Limits that keep one hostile PDF or link from holding a server thread or its memory."""

from __future__ import annotations

import os
import socket
import threading
import time
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from lemma import ingest

LINE = b"(AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA) Tj "


def make_pdf(pages: int, lines_per_page: int, padding: int = 0) -> bytes:
    """A PDF whose pages all share one Flate-compressed content stream of repeated text operators.
    A large `lines_per_page` makes a few KB of file expand to megabytes of text per page."""
    body = b"BT /F1 12 Tf 0 0 Td " + LINE * lines_per_page + b"ET"
    comp = zlib.compress(body, 9)
    kids = " ".join(f"{5 + i} 0 R" for i in range(pages)).encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(pages).encode() + b" >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(comp)).encode() + b" /Filter /FlateDecode >>\nstream\n" + comp + b"\nendstream",
    ]
    objs += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 3 0 R >> >> >>"] * pages
    out = b"%PDF-1.4\n" + (b"%" + b"x" * padding + b"\n" if padding else b"")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


BOMB = make_pdf(pages=4, lines_per_page=50_000)  # about 10 KB that expands to 2.6 MB of text per page
SMALL = make_pdf(pages=1, lines_per_page=20)


class PdfLimits(unittest.TestCase):
    def test_a_pdf_bomb_stops_at_the_deadline_and_frees_its_reader_slot(self):
        with patch.object(ingest, "PDF_DEADLINE", 2, create=True):
            start = time.monotonic()
            with self.assertRaises(ingest.IngestError):
                ingest.from_bytes(BOMB)
            self.assertLess(time.monotonic() - start, 5)
        with patch.object(ingest, "READER_WAIT", 0.5, create=True):
            for _ in range(3):  # more reads than reader slots, so a leaked slot would show as "busy"
                self.assertEqual(ingest.from_bytes(SMALL).pages, 1)

    def test_a_reader_waiting_for_a_slot_gives_up_with_a_plain_message(self):
        errors, reading, finish = [], threading.Semaphore(0), threading.Event()
        real_read = ingest._read_pdf_in_child

        def slow_read(data):  # holds its slot until the test lets it go, however fast the computer is
            if data is BOMB:
                reading.release()
                finish.wait(10)
                raise ingest.IngestError("This PDF took too long to read.")
            return real_read(data)

        def read_bomb():
            try:
                ingest.from_bytes(BOMB)
            except ingest.IngestError as e:
                errors.append(e)

        with patch.object(ingest, "_read_pdf_in_child", slow_read), patch.object(ingest, "READER_WAIT", 0.5, create=True):
            busy = [threading.Thread(target=read_bomb) for _ in range(2)]
            for t in busy:
                t.start()
            for _ in busy:
                self.assertTrue(reading.acquire(timeout=5))
            start = time.monotonic()
            with self.assertRaisesRegex(ingest.IngestError, "busy"):
                ingest.from_bytes(SMALL)
            self.assertLess(time.monotonic() - start, 2)
            finish.set()
            for t in busy:
                t.join()
            self.assertEqual(ingest.from_bytes(SMALL).pages, 1)  # both slots were freed
        self.assertEqual(len(errors), 2)

    def test_only_the_first_pages_are_read(self):
        with patch.object(ingest, "MAX_PDF_PAGES", 5, create=True):
            paper = ingest.from_bytes(make_pdf(pages=8, lines_per_page=20))
        self.assertEqual(paper.pages, 5)
        self.assertEqual(paper.text.count("A"), 5 * 20 * 46)

    def test_pdf_text_is_capped(self):
        with patch.object(ingest, "MAX_CHARS", 5000, create=True):
            paper = ingest.from_bytes(make_pdf(pages=3, lines_per_page=200))
        self.assertLessEqual(len(paper.text), 5000)
        self.assertGreater(len(paper.text), 4000)

    def test_a_scanned_pdf_still_gets_the_scanned_message(self):
        with self.assertRaisesRegex(ingest.IngestError, "scanned image"):
            ingest.from_bytes(make_pdf(pages=1, lines_per_page=1))


class TextLimits(unittest.TestCase):
    def test_web_page_text_is_capped(self):
        page = b"<html><body>" + b"<p>" + b"plenty of words here " * 2000 + b"</p></body></html>"
        with patch.object(ingest, "MAX_CHARS", 5000, create=True):
            self.assertLessEqual(len(ingest.from_bytes(page, content_type="text/html").text), 5000)
            self.assertLessEqual(len(ingest.from_bytes(b"plain words " * 2000, content_type="text/plain").text), 5000)


class Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        try:
            self.routes[self.path](self)
        except (BrokenPipeError, ConnectionResetError):
            pass


def drip_body(h):
    h.send_response(200)
    h.send_header("Content-Type", "text/html")
    h.end_headers()
    for _ in range(40):  # one byte every half second: each read is quick, the whole page never ends
        h.wfile.write(b"<")
        h.wfile.flush()
        time.sleep(0.5)


def drip_headers(h):
    h.wfile.write(b"HTTP/1.1 200 OK\r\n")
    for _ in range(40):
        h.wfile.write(b"X")
        h.wfile.flush()
        time.sleep(0.5)


def huge_html(h):
    h.send_response(200)
    h.send_header("Content-Type", "text/html")
    h.end_headers()
    h.wfile.write(b"<html><body>")
    chunk = b"<p>" + b"word " * 2000 + b"</p>"
    for _ in range(12 * 1024 * 1024 // len(chunk)):
        h.wfile.write(chunk)


def large_pdf(h):
    data = make_pdf(pages=1, lines_per_page=20, padding=12 * 1024 * 1024)
    h.send_response(200)
    h.send_header("Content-Type", "application/pdf")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


Handler.routes = {"/drip": drip_body, "/drip-headers": drip_headers, "/huge.html": huge_html, "/big.pdf": large_pdf}


class LinkLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://pub.test:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        orig = ingest._public_addresses

        def pretend_public(host, port):  # "pub.test" stands for a public site served by this test
            if host == "pub.test":
                return socket.getaddrinfo("127.0.0.1", port, type=socket.SOCK_STREAM)
            return orig(host, port)

        p = patch.object(ingest, "_public_addresses", pretend_public)
        p.start()
        self.addCleanup(p.stop)

    def assert_gives_up_in_time(self, path):
        with patch.object(ingest, "FETCH_DEADLINE", 2, create=True):
            start = time.monotonic()
            with self.assertRaisesRegex(ingest.IngestError, "too long"):
                ingest.from_url(self.base + path)
            self.assertLess(time.monotonic() - start, 3.5)

    def test_a_slow_drip_body_stops_at_the_total_deadline(self):
        self.assert_gives_up_in_time("/drip")

    def test_slow_drip_headers_stop_at_the_total_deadline(self):
        self.assert_gives_up_in_time("/drip-headers")

    def test_first_readable_budget_bounds_a_slow_link(self):
        start = time.monotonic()
        with self.assertRaises(ingest.IngestError):
            ingest.first_readable([self.base + "/drip"], timeout=30, budget=2)
        self.assertLess(time.monotonic() - start, 3.5)

    def test_an_oversized_web_page_is_refused(self):
        with self.assertRaisesRegex(ingest.IngestError, "10 MB"):
            ingest.from_url(self.base + "/huge.html")

    def test_a_pdf_over_the_page_limit_still_downloads(self):
        self.assertEqual(ingest.from_url(self.base + "/big.pdf").pages, 1)


class AddressGuard(unittest.TestCase):
    def test_ipv6_forms_of_private_addresses_are_refused(self):
        for host in ("64:ff9b::7f00:1", "::127.0.0.1", "::ffff:127.0.0.1", "2002:7f00:1::", "64:ff9b::a9fe:a9fe"):
            with self.subTest(host=host), self.assertRaisesRegex(ingest.IngestError, "public web addresses"):
                ingest.from_url(f"http://[{host}]:9/paper.pdf")

    def test_an_unknown_host_reads_the_same_as_a_private_one(self):
        with self.assertRaises(ingest.IngestError) as private:
            ingest.from_url("http://10.0.0.1:9/paper.pdf")
        with patch.object(ingest.socket, "getaddrinfo", side_effect=socket.gaierror("no such host")):
            with self.assertRaises(ingest.IngestError) as unknown:
                ingest.from_url("http://intranet.corp:9/paper.pdf")
        self.assertEqual(str(unknown.exception), str(private.exception))


if __name__ == "__main__":
    unittest.main()


class SharedLimitTests(unittest.TestCase):
    def test_downloads_share_one_limit_and_give_up_when_it_is_full(self):
        held = threading.BoundedSemaphore(1)
        held.acquire()
        with patch.object(ingest, "_DOWNLOADS", held):
            started = time.time()
            with self.assertRaisesRegex(ingest.IngestError, "busy"):
                ingest.from_url("https://example.org/paper", timeout=0.3)
            self.assertLess(time.time() - started, 2)

    def test_the_pdf_reader_gets_no_secrets(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "secret", "LEMMA_GOOGLE_CLIENT_SECRET": "s2"}):
            env = ingest._child_env()
        self.assertNotIn("TYPESAFE_API_KEY", env)
        self.assertNotIn("LEMMA_GOOGLE_CLIENT_SECRET", env)
