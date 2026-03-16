"""Unit tests for deterministic PDF artifact extraction service."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.pdf_artifact_extractor import PDFArtifactExtractor


class _FakeEmbeddedImage:
    def __init__(self, *, data: bytes, name: str, width: int, height: int) -> None:
        self.data = data
        self.name = name
        self.image = SimpleNamespace(width=width, height=height)


class _FakePage:
    def __init__(self, images: list[_FakeEmbeddedImage]) -> None:
        self.images = images


class _FakeReader:
    def __init__(self, _path: str) -> None:
        self.pages = [
            _FakePage(
                [
                    _FakeEmbeddedImage(
                        data=(
                            b"\x89PNG\r\n\x1a\n"
                            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDAT"
                            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00"
                            b"\x00\x00\x00IEND\xaeB`\x82"
                        ),
                        name="figure_1.png",
                        width=640,
                        height=360,
                    )
                ]
            )
        ]


class _FakeReaderNoImages:
    def __init__(self, _path: str) -> None:
        self.pages = [_FakePage([])]


class PDFArtifactExtractorTest(unittest.TestCase):
    def test_extract_embedded_images_writes_assets(self) -> None:
        extractor = PDFArtifactExtractor()

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            pdf_path = run_dir / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n%mock\n")

            with patch("app.services.pdf_artifact_extractor.importlib.import_module") as mocked_import:
                mocked_import.return_value = SimpleNamespace(PdfReader=_FakeReader)
                result = extractor.extract(pdf_path=pdf_path, output_dir=run_dir)

            self.assertEqual(len(result.extracted_assets), 1)
            extracted = result.extracted_assets[0]
            self.assertEqual(extracted.asset_id, "SRC_P01_IMG01")
            self.assertEqual(extracted.page_number, 1)
            self.assertEqual(extracted.width, 640)
            self.assertEqual(extracted.height, 360)
            self.assertTrue(Path(extracted.file_path).is_file())

    def test_extract_without_embedded_images_returns_warning(self) -> None:
        extractor = PDFArtifactExtractor()

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            pdf_path = run_dir / "source.pdf"
            pdf_path.write_bytes(b"%PDF-1.7\n%mock\n")

            with patch("app.services.pdf_artifact_extractor.importlib.import_module") as mocked_import:
                mocked_import.return_value = SimpleNamespace(PdfReader=_FakeReaderNoImages)
                result = extractor.extract(pdf_path=pdf_path, output_dir=run_dir)

            self.assertEqual(result.extracted_assets, [])
            self.assertTrue(any("No embedded images were extracted" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
