"""The PDF reader's child process, run in this process: a PDF on stdin, its text or the reason it failed as JSON on stdout.

The real child starts with -I and a minimal environment, so these are what show its contract to coverage.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest import mock

from lemma import ingest
from test_ingest_hardening import make_pdf
from test_pdf_passwords import encrypted


def run_child(data: bytes, max_pages: int = 50, max_chars: int = 100_000, max_memory: int = 0) -> dict:
    stdin = mock.Mock(buffer=io.BytesIO(data))
    with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", io.StringIO()) as out:
        ingest._pdf_child(max_pages, max_chars, max_memory)
    return json.loads(out.getvalue())


class PdfChildTests(unittest.TestCase):
    def test_a_pdf_comes_back_as_its_text_and_page_count(self):
        found = run_child(make_pdf(3, 20))
        self.assertEqual(found["pages"], 3)
        self.assertEqual(found["text"].count("\n\n"), 2)

    def test_the_page_and_character_limits_stop_reading(self):
        self.assertEqual(run_child(make_pdf(5, 20), max_pages=2)["pages"], 2)
        found = run_child(make_pdf(5, 20), max_chars=50)
        self.assertEqual(found["pages"], 1)
        self.assertLessEqual(len(found["text"]), 50)

    def test_failures_come_back_as_a_message(self):
        self.assertEqual(run_child(b"not a pdf at all")["error"], "Couldn't read this PDF (PdfStreamError).")
        self.assertEqual(run_child(encrypted("secret"))["error"], "This PDF is password-protected.")

    def test_running_out_of_memory_says_the_pdf_is_too_complex(self):
        with mock.patch.object(ingest, "_read_pdf", side_effect=MemoryError):
            self.assertIn("too complex", run_child(make_pdf(1, 20))["error"])

    def test_a_memory_limit_the_platform_refuses_is_skipped(self):
        import resource

        with mock.patch.object(resource, "setrlimit", side_effect=ValueError) as limit:
            self.assertEqual(run_child(make_pdf(1, 20), max_memory=1 << 30)["pages"], 1)
        limit.assert_called_once_with(resource.RLIMIT_AS, (1 << 30, 1 << 30))

    def test_a_password_check_that_raises_counts_as_locked(self):
        from pypdf import PdfReader

        with mock.patch.object(PdfReader, "decrypt", side_effect=NotImplementedError):
            self.assertEqual(run_child(encrypted(""))["error"], "This PDF is password-protected.")

    def test_unreadable_metadata_leaves_the_title_empty(self):
        from pypdf import PdfReader

        with mock.patch.object(PdfReader, "metadata", new_callable=mock.PropertyMock, side_effect=ValueError):
            self.assertEqual(run_child(make_pdf(1, 20))["title"], "")


if __name__ == "__main__":
    unittest.main()
