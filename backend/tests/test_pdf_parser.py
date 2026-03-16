"""Unit tests for the minimal PDFParser service."""

from __future__ import annotations

import types
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.pdf_parser import PDFParser


class PDFParserTest(unittest.TestCase):
    def test_parse_extracts_page_texts_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            page_one = MagicMock()
            page_one.extract_text.return_value = "First page text"
            page_two = MagicMock()
            page_two.extract_text.return_value = ""

            fake_reader = MagicMock()
            fake_reader.pages = [page_one, page_two]

            fake_module = types.SimpleNamespace(PdfReader=MagicMock(return_value=fake_reader))
            with patch("app.services.pdf_parser.importlib.import_module", return_value=fake_module):
                result = PDFParser().parse(pdf_path)

            self.assertEqual(result.page_count, 2)
            self.assertEqual(result.page_texts[0], "First page text")
            self.assertIn("First page text", result.combined_text)
            self.assertTrue(any("No extractable text found on page 2" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
