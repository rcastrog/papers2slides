"""Unit tests for run results payload normalization."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.runs import _build_results_payload


class RunsRoutesResultsPayloadTests(unittest.TestCase):
    def test_build_results_payload_fills_missing_fields_from_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            notes_path = run_path / "presentation" / "speaker_notes.json"
            notes_path.parent.mkdir(parents=True, exist_ok=True)
            notes_path.write_text("{}", encoding="utf-8")

            payload = _build_results_payload(
                run_id="api-job_1",
                run_path=run_path,
                results={
                    "audit_report_path": "audit/audit_report_initial.json",
                    "final_risk_summary": {"deck_risk_level": "high"},
                },
                workflow_summary={
                    "final_output_paths_after_repair": {
                        "reveal_entry_html": "presentation/reveal/index.html",
                        "pptx_path": "presentation/pptx/deck.pptx",
                    },
                    "unresolved_high_severity_findings_count": 1,
                    "deck_risk_level_final": "medium",
                },
            )

            self.assertEqual(payload["run_id"], "api-job_1")
            self.assertEqual(payload["reveal_path"], "presentation/reveal/index.html")
            self.assertEqual(payload["pptx_path"], "presentation/pptx/deck.pptx")
            self.assertEqual(payload["notes_path"], str(notes_path))
            self.assertEqual(payload["final_risk_summary"]["deck_risk_level"], "high")
            self.assertEqual(payload["final_risk_summary"]["unresolved_high_severity_findings_count"], 1)

    def test_build_results_payload_uses_defaults_when_missing_everything(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)

            payload = _build_results_payload(
                run_id="api-job_2",
                run_path=run_path,
                results=None,
                workflow_summary=None,
            )

            self.assertEqual(payload["run_id"], "api-job_2")
            self.assertIsNone(payload["reveal_path"])
            self.assertIsNone(payload["pptx_path"])
            self.assertIsNone(payload["notes_path"])
            self.assertIsNone(payload["audit_report_path"])
            self.assertIn("final_risk_summary", payload)
            self.assertIn("asset_usage_summary", payload)


if __name__ == "__main__":
    unittest.main()
