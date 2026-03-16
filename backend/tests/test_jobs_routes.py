"""Unit tests for API job route failure manifest behavior."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.jobs import _build_failed_manifest, _load_json_dict


class JobRoutesFailureManifestTest(unittest.TestCase):
    def test_build_failed_manifest_preserves_latest_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            logs_dir = run_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            latest_manifest = {
                "run_id": "api-job_123",
                "status": "running",
                "current_stage": "A11",
                "completed_stages": ["A0", "A1", "A2"],
                "warnings": [],
                "errors": ["prior warning"],
                "artifacts": {},
                "checkpoint_state": {},
            }
            (logs_dir / "run_manifest.json").write_text(json.dumps(latest_manifest), encoding="utf-8")

            fallback_manifest = {
                "run_id": "api-job_123",
                "status": "running",
                "current_stage": "A0",
                "completed_stages": [],
                "warnings": [],
                "errors": [],
                "artifacts": {},
                "checkpoint_state": {},
            }

            failed_manifest = _build_failed_manifest(
                run_path=run_path,
                fallback=fallback_manifest,
                error=RuntimeError("audit validation failed"),
            )

            self.assertEqual(failed_manifest["status"], "failed")
            self.assertEqual(failed_manifest["current_stage"], "A11")
            self.assertEqual(failed_manifest["failed_stage"], "A11")
            self.assertEqual(failed_manifest["completed_stages"], ["A0", "A1", "A2"])
            self.assertIn("prior warning", failed_manifest["errors"])
            self.assertIn("audit validation failed", failed_manifest["errors"])

    def test_load_json_dict_returns_empty_on_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "broken.json"
            target.write_text("not-json", encoding="utf-8")
            self.assertEqual(_load_json_dict(target), {})


if __name__ == "__main__":
    unittest.main()
