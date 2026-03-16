"""Minimal local PDF text extraction service."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PDFParseOutput:
    """Structured output for page-wise PDF text extraction."""

    pdf_path: Path
    page_count: int
    page_texts: list[str]
    combined_text: str
    warnings: list[str]


class PDFParser:
    """Extract text from local PDFs page-by-page without OCR."""

    def parse(self, pdf_path: Path) -> PDFParseOutput:
        """Parse a PDF path and return a resilient extraction result."""
        resolved_path = pdf_path.expanduser().resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"PDF file not found: {resolved_path}")

        try:
            pypdf_module = importlib.import_module("pypdf")
            pdf_reader_cls = getattr(pypdf_module, "PdfReader")
        except Exception as exc:
            raise RuntimeError("pypdf is required for PDF parsing. Install it with 'pip install pypdf'.") from exc

        warnings: list[str] = []
        try:
            reader = pdf_reader_cls(str(resolved_path))
        except Exception as exc:  # pragma: no cover - library-level parsing errors vary.
            raise RuntimeError(f"Failed to open PDF: {resolved_path}") from exc

        page_texts: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                extracted_text = page.extract_text() or ""
            except Exception as exc:  # pragma: no cover - extraction errors vary by file.
                extracted_text = ""
                warnings.append(f"Failed to extract text from page {page_number}: {exc}")

            if not extracted_text.strip():
                warnings.append(f"No extractable text found on page {page_number}")
            page_texts.append(extracted_text)

        combined_text = "\n\n".join(text for text in page_texts if text.strip())
        if not combined_text.strip():
            warnings.append("Combined extracted text is empty")

        return PDFParseOutput(
            pdf_path=resolved_path,
            page_count=len(page_texts),
            page_texts=page_texts,
            combined_text=combined_text,
            warnings=warnings,
        )
