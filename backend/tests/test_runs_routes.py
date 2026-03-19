"""Unit tests for run results payload normalization."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import BackgroundTasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.runs import (
    _build_results_payload,
    _build_retry_configuration,
    cancel_run,
    _finalize_stalled_manifest_if_needed,
    _find_source_pdf_for_retry,
    retry_run,
    _resolve_child_path,
    _resolve_reveal_asset_path,
    _resolve_reveal_index_path,
)


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
            self.assertIn("repetition_metrics", payload)

    def test_build_results_payload_backfills_repetition_metrics_from_presentation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            plan_path = run_path / "presentation" / "presentation_plan.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(
                """
{
    "deck_metadata": {
        "title": "Deck",
        "subtitle": "Sub",
        "language": "en",
        "presentation_style": "journal_club",
        "target_audience": "research_specialists",
        "target_duration_minutes": 20,
        "target_slide_count": 2
    },
    "narrative_arc": {
        "overall_story": "Story",
        "audience_adaptation_notes": [],
        "language_adaptation_notes": []
    },
    "slides": [
        {
            "slide_number": 1,
            "slide_role": "result",
            "title": "Results",
            "objective": "Explain",
            "key_points": [
                "Observed exposure links capability and real-world usage.",
                "Observed exposure links capability and real-world usage.",
                "Signal A",
                "Signal B"
            ],
            "must_avoid": [],
            "visuals": [],
            "source_support": [],
            "citations": [
                {"short_citation": "Smith, 2024", "source_kind": "reference_paper", "citation_purpose": "contextual_reference"}
            ],
            "speaker_note_hooks": [],
            "confidence_notes": [],
            "layout_hint": "default"
        },
        {
            "slide_number": 2,
            "slide_role": "discussion",
            "title": "Discussion",
            "objective": "Discuss",
            "key_points": ["Signal C", "Signal D", "Signal E", "Signal F"],
            "must_avoid": [],
            "visuals": [],
            "source_support": [],
            "citations": [
                {"short_citation": "Smith, 2024", "source_kind": "reference_paper", "citation_purpose": "contextual_reference"}
            ],
            "speaker_note_hooks": [],
            "confidence_notes": [],
            "layout_hint": "default"
        }
    ],
    "global_warnings": [],
    "plan_confidence": "medium"
}
                """.strip(),
                encoding="utf-8",
            )

            payload = _build_results_payload(
                run_id="api-job-3",
                run_path=run_path,
                results={
                    "final_risk_summary": {},
                    "asset_usage_summary": {},
                },
                workflow_summary=None,
            )

            self.assertIn("repetition_metrics", payload)
            self.assertGreater(payload["repetition_metrics"]["bullet"]["total"], 0)
            self.assertGreaterEqual(payload["repetition_metrics"]["citation"]["total_mentions"], 2)

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

    def test_finalize_stalled_manifest_marks_failed_when_stuck_mid_stage(self) -> None:
        manifest = {
            "run_id": "api-job-mid-stage-stalled",
            "status": "running",
            "current_stage": "A5",
            "completed_stages": ["A0", "A1", "A2", "A3", "A4"],
            "stages": [
                {"stage": "A0", "status": "completed"},
                {"stage": "A4", "status": "completed"},
            ],
            "errors": [],
        }

        normalized, changed = _finalize_stalled_manifest_if_needed(manifest, stale_seconds=3600.0)

        self.assertTrue(changed)
        self.assertEqual(normalized["status"], "failed")
        self.assertEqual(normalized["failed_stage"], "A5")
        self.assertTrue(any("stalling during A5" in msg for msg in normalized.get("errors", [])))

    def test_finalize_stalled_manifest_keeps_running_entry_before_in_stage_timeout(self) -> None:
        manifest = {
            "run_id": "api-job-mid-stage-active",
            "status": "running",
            "current_stage": "A5",
            "completed_stages": ["A0", "A1", "A2", "A3", "A4"],
            "stages": [
                {"stage": "A4", "status": "completed"},
                {"stage": "A5", "status": "running"},
            ],
            "errors": [],
        }

        normalized, changed = _finalize_stalled_manifest_if_needed(manifest, stale_seconds=900.0)

        self.assertFalse(changed)
        self.assertEqual(normalized["status"], "running")

    def test_finalize_stalled_manifest_fails_running_entry_after_in_stage_timeout(self) -> None:
        manifest = {
            "run_id": "api-job-mid-stage-timeout",
            "status": "running",
            "current_stage": "A5",
            "completed_stages": ["A0", "A1", "A2", "A3", "A4"],
            "stages": [
                {"stage": "A4", "status": "completed"},
                {"stage": "A5", "status": "running"},
            ],
            "errors": [],
        }

        normalized, changed = _finalize_stalled_manifest_if_needed(manifest, stale_seconds=3600.0)

        self.assertTrue(changed)
        self.assertEqual(normalized["status"], "failed")
        self.assertEqual(normalized["failed_stage"], "A5")
        self.assertTrue(any("stalling during A5" in msg for msg in normalized.get("errors", [])))

    def test_build_retry_configuration_prefers_job_spec_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            input_dir = run_path / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "job_spec.json").write_text(
                '{"presentation_style":"chalk_talk","audience":"mixed","language":"es",'
                '"output_formats":["reveal"],"repair_on_audit":true,'
                '"advanced_options":{"target_slide_count":10}}',
                encoding="utf-8",
            )

            manifest = {
                "run_summary": {
                    "job_summary": {
                        "presentation_style": "journal_club",
                        "target_audience": "research_specialists",
                        "language": "en",
                        "output_formats": ["reveal", "pptx"],
                        "advanced_options": {"llm_temperature": 0.0},
                        "repair_on_audit": False,
                    }
                }
            }

            workflow_options, repair_on_audit = _build_retry_configuration(run_path, manifest)

            self.assertEqual(workflow_options["presentation_style"], "chalk_talk")
            self.assertEqual(workflow_options["audience"], "mixed")
            self.assertEqual(workflow_options["language"], "es")
            self.assertEqual(workflow_options["output_formats"], ["reveal"])
            self.assertEqual(workflow_options["advanced_options"]["target_slide_count"], 10)
            self.assertEqual(workflow_options["advanced_options"]["llm_temperature"], 0.0)
            self.assertTrue(repair_on_audit)

    def test_find_source_pdf_for_retry_prefers_source_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            input_dir = run_path / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "uploaded.pdf").write_bytes(b"uploaded")
            source_pdf = input_dir / "source.pdf"
            source_pdf.write_bytes(b"source")

            found = _find_source_pdf_for_retry(run_path)
            self.assertEqual(found, source_pdf)

    def test_resolve_reveal_index_path_falls_back_to_reveal_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            repaired_index = run_path / "presentation" / "reveal_repaired" / "index.html"
            repaired_index.parent.mkdir(parents=True, exist_ok=True)
            repaired_index.write_text("<html>repaired</html>", encoding="utf-8")

            resolved = _resolve_reveal_index_path(run_path=run_path, selected_path=None)

            self.assertEqual(resolved, repaired_index)

    def test_resolve_reveal_asset_path_reads_from_reveal_repaired_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            asset_file = run_path / "presentation" / "reveal_repaired" / "assets" / "deck.css"
            asset_file.parent.mkdir(parents=True, exist_ok=True)
            asset_file.write_text("body{}", encoding="utf-8")

            resolved = _resolve_reveal_asset_path(run_path=run_path, asset_path="deck.css")

            self.assertEqual(resolved, asset_file)

    def test_retry_run_accepts_failed_with_quality_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runs_root = Path(temp_dir)
            run_path = runs_root / "api-job_0001"
            (run_path / "logs").mkdir(parents=True, exist_ok=True)
            (run_path / "input").mkdir(parents=True, exist_ok=True)
            (run_path / "input" / "source.pdf").write_bytes(b"pdf")

            manifest = {
                "run_id": "api-job_0001",
                "status": "failed_with_quality_gate",
                "run_summary": {
                    "job_summary": {
                        "presentation_style": "journal_club",
                        "target_audience": "research_specialists",
                        "language": "en",
                        "output_formats": ["reveal", "pptx"],
                        "advanced_options": {},
                        "repair_on_audit": True,
                    }
                },
            }
            (run_path / "logs" / "run_manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            original_resolve = retry_run.__globals__["_resolve_run_path"]
            original_execute = retry_run.__globals__["_execute_workflow"]
            original_manager = retry_run.__globals__["RunManager"]

            class _StubManager:
                def __init__(self, root: Path) -> None:
                    self.root = root

                def create_run(self, slug: str = "api-job") -> Path:
                    path = self.root / "api-job_0002"
                    path.mkdir(parents=True, exist_ok=True)
                    return path

                def save_json(self, relative_path: str, payload: dict) -> None:
                    path = (self.root / "api-job_0002" / relative_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(payload), encoding="utf-8")

            try:
                retry_run.__globals__["_resolve_run_path"] = lambda _run_id: run_path
                retry_run.__globals__["_execute_workflow"] = lambda *args, **kwargs: None
                retry_run.__globals__["RunManager"] = lambda _root: _StubManager(runs_root)

                response = retry_run("api-job_0001", BackgroundTasks())
                self.assertEqual(response.status, "queued")
                self.assertEqual(response.run_id, "api-job_0002")
            finally:
                retry_run.__globals__["_resolve_run_path"] = original_resolve
                retry_run.__globals__["_execute_workflow"] = original_execute
                retry_run.__globals__["RunManager"] = original_manager

    def test_cancel_run_treats_failed_with_quality_gate_as_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "logs").mkdir(parents=True, exist_ok=True)
            (run_path / "logs" / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "api-job-terminal",
                        "status": "failed_with_quality_gate",
                    }
                ),
                encoding="utf-8",
            )

            original_resolve = cancel_run.__globals__["_resolve_run_path"]
            original_manager = cancel_run.__globals__["_resolve_run_manager"]

            class _NoopManager:
                def save_json(self, *_args, **_kwargs) -> None:
                    raise AssertionError("save_json should not be called for terminal status")

            try:
                cancel_run.__globals__["_resolve_run_path"] = lambda _run_id: run_path
                cancel_run.__globals__["_resolve_run_manager"] = lambda _run_path: _NoopManager()

                response = cancel_run("api-job-terminal")
                self.assertEqual(response["status"], "failed_with_quality_gate")
                self.assertIn("already terminal", response["message"])
            finally:
                cancel_run.__globals__["_resolve_run_path"] = original_resolve
                cancel_run.__globals__["_resolve_run_manager"] = original_manager


if __name__ == "__main__":
    unittest.main()
