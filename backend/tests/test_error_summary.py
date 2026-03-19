"""Tests for compact exception summaries used in run manifests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.utils.error_summary import summarize_exception_for_logs


class _FakeValidationError(Exception):
    def __init__(self) -> None:
        super().__init__("very long pydantic message that should not be emitted as-is")
        self.title = "ReferenceSummary"

    def errors(self) -> list[dict[str, object]]:
        return [
            {"loc": ("reference_id",), "type": "missing"},
            {"loc": ("reference_title",), "type": "missing"},
            {"loc": ("deck_language",), "type": "extra_forbidden"},
            {"loc": ("slide_notes",), "type": "extra_forbidden"},
        ]


class ErrorSummaryTest(unittest.TestCase):
    def test_validation_error_is_summarized(self) -> None:
        summary = summarize_exception_for_logs(_FakeValidationError())
        self.assertIn("ReferenceSummary validation failed", summary)
        self.assertIn("missing fields", summary)
        self.assertIn("unexpected fields", summary)
        self.assertNotIn("https://errors.pydantic.dev", summary)

    def test_generic_error_is_single_line_and_trimmed(self) -> None:
        error = RuntimeError("line one\nline two")
        summary = summarize_exception_for_logs(error, limit=32)
        self.assertNotIn("\n", summary)
        self.assertTrue(len(summary) <= 32)


if __name__ == "__main__":
    unittest.main()
