"""Deterministic V1 extraction of source-paper image artifacts from PDFs."""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ExtractedAsset:
    """One extracted visual asset from a source PDF."""

    asset_id: str
    file_path: str
    page_number: int
    extraction_method: str
    width: int | None
    height: int | None
    notes: list[str]


@dataclass(slots=True)
class ExtractedArtifactBundle:
    """All extracted assets plus extraction warnings."""

    extracted_assets: list[ExtractedAsset]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "extracted_assets": [asdict(asset) for asset in self.extracted_assets],
            "warnings": list(self.warnings),
        }


class PDFArtifactExtractor:
    """Extract embedded page images in a conservative deterministic V1 pass."""

    def extract(self, pdf_path: Path, output_dir: Path) -> ExtractedArtifactBundle:
        """Extract embedded images and write them under artifacts/source/figures."""
        warnings: list[str] = []
        extracted_assets: list[ExtractedAsset] = []

        source_pdf = pdf_path.expanduser().resolve()
        if not source_pdf.is_file():
            return ExtractedArtifactBundle(
                extracted_assets=[],
                warnings=[f"PDF file not found for artifact extraction: {source_pdf}"],
            )

        figures_dir = (output_dir / "artifacts" / "source" / "figures").resolve()
        figures_dir.mkdir(parents=True, exist_ok=True)

        try:
            pypdf_module = importlib.import_module("pypdf")
            pdf_reader_cls = getattr(pypdf_module, "PdfReader")
        except Exception as exc:
            return ExtractedArtifactBundle(
                extracted_assets=[],
                warnings=[f"pypdf is required for artifact extraction: {exc}"],
            )

        try:
            reader = pdf_reader_cls(str(source_pdf))
        except Exception as exc:
            return ExtractedArtifactBundle(
                extracted_assets=[],
                warnings=[f"Failed to open PDF for artifact extraction: {exc}"],
            )

        for page_number, page in enumerate(getattr(reader, "pages", []), start=1):
            images = getattr(page, "images", None)
            if images is None:
                continue

            try:
                image_items = list(images)
            except Exception as exc:
                warnings.append(f"Failed to iterate embedded images on page {page_number}: {exc}")
                continue

            for image_index, image_obj in enumerate(image_items, start=1):
                image_bytes, preferred_extension = self._extract_image_payload(image_obj)
                if image_bytes is None:
                    warnings.append(f"Skipped unreadable embedded image on page {page_number}, index {image_index}")
                    continue

                extension = preferred_extension or self._infer_extension(image_obj, image_bytes)
                asset_id = f"SRC_P{page_number:02d}_IMG{image_index:02d}"
                target_path = figures_dir / f"{asset_id}{extension}"
                target_path.write_bytes(image_bytes)

                width, height = self._extract_dimensions(image_obj)
                notes = self._extract_notes(image_obj)
                extracted_assets.append(
                    ExtractedAsset(
                        asset_id=asset_id,
                        file_path=str(target_path),
                        page_number=page_number,
                        extraction_method="embedded_image",
                        width=width,
                        height=height,
                        notes=notes,
                    )
                )

        if not extracted_assets:
            warnings.append("No embedded images were extracted from the source PDF in V1.")

        return ExtractedArtifactBundle(extracted_assets=extracted_assets, warnings=warnings)

    @staticmethod
    def _extract_image_payload(image_obj: Any) -> tuple[bytes | None, str | None]:
        """Return image bytes plus preferred extension for web-friendly downstream rendering.

        We prefer decoded PIL output when available to avoid carrying source encodings
        (e.g. JPEG2000) that many browsers won't render directly.
        """
        image = getattr(image_obj, "image", None)
        if image is not None:
            try:
                if str(getattr(image, "mode", "")).upper() in {"RGBA", "LA", "P"}:
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    return (buffer.getvalue(), ".png")

                buffer = BytesIO()
                image.save(buffer, format="JPEG")
                return (buffer.getvalue(), ".jpg")
            except Exception:
                # Fall back to raw bytes when PIL conversion fails.
                pass

        data = getattr(image_obj, "data", None)
        if isinstance(data, (bytes, bytearray)):
            return (bytes(data), None)

        if isinstance(image_obj, (bytes, bytearray)):
            return (bytes(image_obj), None)

        return (None, None)

    @staticmethod
    def _infer_extension(image_obj: Any, image_bytes: bytes) -> str:
        name = str(getattr(image_obj, "name", "")).lower()
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
            if name.endswith(ext):
                return ext

        if image_bytes.startswith(b"\x89PNG"):
            return ".png"
        if image_bytes.startswith(b"\xff\xd8"):
            return ".jpg"
        if image_bytes.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n"):
            return ".jp2"
        if image_bytes.startswith(b"GIF8"):
            return ".gif"
        if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return ".webp"
        if image_bytes.startswith(b"BM"):
            return ".bmp"
        return ".bin"

    @staticmethod
    def _extract_dimensions(image_obj: Any) -> tuple[int | None, int | None]:
        image = getattr(image_obj, "image", None)
        width = getattr(image, "width", None)
        height = getattr(image, "height", None)
        if isinstance(width, int) and isinstance(height, int):
            return width, height
        return None, None

    @staticmethod
    def _extract_notes(image_obj: Any) -> list[str]:
        notes: list[str] = []
        name = getattr(image_obj, "name", None)
        if isinstance(name, str) and name.strip():
            notes.append(f"pdf_image_name={name}")
        return notes
