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

from app.api.routes.runs import _build_results_payload, _finalize_stalled_manifest_if_needed, _resolve_child_path


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

    def test_resolve_child_path_accepts_run_relative_reveal_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            reveal_index = run_path / "presentation" / "reveal" / "index.html"
            reveal_index.parent.mkdir(parents=True, exist_ok=True)
            reveal_index.write_text("<html></html>", encoding="utf-8")

            resolved = _resolve_child_path(
                base_dir=(run_path / "presentation" / "reveal").resolve(),
                candidate_path="presentation/reveal/index.html",
                run_path=run_path,
            )

            self.assertEqual(resolved, reveal_index.resolve())

    def test_resolve_child_path_blocks_traversal_outside_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            assets_root = run_path / "presentation" / "reveal" / "assets"
            assets_root.mkdir(parents=True, exist_ok=True)
            outside_file = run_path / "presentation" / "reveal" / "index.html"
            outside_file.parent.mkdir(parents=True, exist_ok=True)
            outside_file.write_text("<html></html>", encoding="utf-8")

            resolved = _resolve_child_path(
                base_dir=assets_root.resolve(),
                candidate_path="../index.html",
                run_path=run_path,
            )

            self.assertIsNone(resolved)

    def test_finalize_stalled_manifest_marks_failed_when_stage_already_completed(self) -> None:
        manifest = {
            "run_id": "api-job-stalled",
            "status": "running",
            "current_stage": "A6",
            "completed_stages": ["A0", "A1", "A2", "A3", "A4", "A5", "A6"],
            "stages": [
                {"stage": "A5", "status": "completed"},
                {"stage": "A6", "status": "completed"},
            ],
            "errors": [],
        }

        normalized, changed = _finalize_stalled_manifest_if_needed(manifest, stale_seconds=900.0)

        self.assertTrue(changed)
        self.assertEqual(normalized["status"], "failed")
        self.assertEqual(normalized["failed_stage"], "A6")
        self.assertTrue(normalized.get("finished_at"))
        self.assertTrue(any("auto-finalized as failed" in msg for msg in normalized.get("errors", [])))

    def test_finalize_stalled_manifest_keeps_recent_running_state(self) -> None:
        manifest = {
            "run_id": "api-job-fresh",
            "status": "running",
            "current_stage": "A6",
            "completed_stages": ["A0", "A1", "A2", "A3", "A4", "A5", "A6"],
            "stages": [
                {"stage": "A6", "status": "completed"},
            ],
            "errors": [],
        }

        normalized, changed = _finalize_stalled_manifest_if_needed(manifest, stale_seconds=30.0)

        self.assertFalse(changed)
        self.assertEqual(normalized["status"], "running")


if __name__ == "__main__":
    unittest.main()
