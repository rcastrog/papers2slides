"""Unit tests for run inspection and artifact read routes."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.main import app


class ArtifactsRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_inspect_endpoint_returns_stage_and_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "logs").mkdir(parents=True, exist_ok=True)
            (run_path / "input").mkdir(parents=True, exist_ok=True)

            manifest = {
                "run_id": "run_test",
                "status": "completed",
                "current_stage": "A11",
                "completed_stages": ["A0", "A1"],
                "stages": [
                    {
                        "stage": "A0",
                        "status": "completed",
                        "started_at": "2026-03-12T00:00:00+00:00",
                        "finished_at": "2026-03-12T00:00:01+00:00",
                        "duration_ms": 1000,
                        "input_artifacts": ["source_paper/source.pdf"],
                        "output_artifacts": ["input/job_spec.json"],
                        "warnings": [],
                        "fallback_used": False,
                        "fallback_reason": None,
                    }
                ],
                "warnings": ["sample warning"],
                "errors": [],
                "artifacts": {"job_spec": "input/job_spec.json"},
                "checkpoint_state": {},
                "started_at": "2026-03-12T00:00:00+00:00",
                "finished_at": "2026-03-12T00:01:00+00:00",
                "duration_ms": 60000,
                "run_summary": {
                    "fallback_stage_count": 0,
                    "audit_findings_count": 1,
                    "unresolved_high_severity_findings_count": 0,
                    "deck_risk_level": "low",
                },
            }

            (run_path / "logs" / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (run_path / "input" / "job_spec.json").write_text(json.dumps({"job_id": "job-1"}), encoding="utf-8")

            with patch("app.api.routes.artifacts._resolve_run_path", return_value=run_path):
                response = self.client.get("/runs/run_test/inspect")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["run_id"], "run_test")
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(len(payload["stages"]), 1)
            self.assertIn("job_spec", payload["artifacts"])
            self.assertEqual(payload["quality_signals"]["fallback_stage_count"], 0)

    def test_artifact_endpoint_returns_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "logs").mkdir(parents=True, exist_ok=True)
            (run_path / "input").mkdir(parents=True, exist_ok=True)

            manifest = {
                "run_id": "run_test",
                "status": "completed",
                "current_stage": "A11",
                "completed_stages": [],
                "stages": [],
                "warnings": [],
                "errors": [],
                "artifacts": {"job_spec": "input/job_spec.json"},
                "checkpoint_state": {},
                "run_summary": {},
            }

            (run_path / "logs" / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (run_path / "input" / "job_spec.json").write_text(json.dumps({"job_id": "job-2"}), encoding="utf-8")

            with patch("app.api.routes.artifacts._resolve_run_path", return_value=run_path):
                response = self.client.get("/runs/run_test/artifacts/job_spec")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["artifact_key"], "job_spec")
            self.assertEqual(payload["content_kind"], "json")
            self.assertEqual(payload["content"]["job_id"], "job-2")

    def test_artifact_endpoint_returns_404_for_unknown_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "logs").mkdir(parents=True, exist_ok=True)
            (run_path / "logs" / "run_manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_test",
                        "status": "completed",
                        "current_stage": "A11",
                        "completed_stages": [],
                        "stages": [],
                        "warnings": [],
                        "errors": [],
                        "artifacts": {},
                        "checkpoint_state": {},
                        "run_summary": {},
                    }
                ),
                encoding="utf-8",
            )

            with patch("app.api.routes.artifacts._resolve_run_path", return_value=run_path):
                response = self.client.get("/runs/run_test/artifacts/not_a_real_key")

            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
