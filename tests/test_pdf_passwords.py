"""Encrypted PDFs: one that needs a password says so; one encrypted with an empty password is read."""

from __future__ import annotations

import io
import unittest

from lemma import ingest
from test_ingest_hardening import make_pdf


def encrypted(password: str) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for p in PdfReader(io.BytesIO(make_pdf(1, 30))).pages:
        writer.add_page(p)
    writer.encrypt(password, algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class EncryptedPdfs(unittest.TestCase):
    def test_password_protected_pdfs_say_so(self):
        with self.assertRaises(ingest.IngestError) as e:
            ingest.from_bytes(encrypted("secret"), filename="locked.pdf")
        self.assertEqual(str(e.exception), "This PDF is password-protected.")

    def test_a_pdf_encrypted_without_a_password_is_read(self):
        self.assertEqual(ingest.from_bytes(encrypted(""), filename="open.pdf").pages, 1)


if __name__ == "__main__":
    unittest.main()
