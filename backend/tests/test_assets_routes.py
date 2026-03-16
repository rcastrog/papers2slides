"""Unit tests for extracted-assets and asset-map API routes."""

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


class AssetsRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_assets_endpoint_returns_normalized_extracted_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            figures_dir = run_path / "artifacts" / "source" / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            image_path = figures_dir / "SRC_P01_IMG01.png"
            image_path.write_bytes(b"png")

            (run_path / "artifacts" / "source").mkdir(parents=True, exist_ok=True)
            (run_path / "artifacts" / "source" / "extracted_assets.json").write_text(
                json.dumps(
                    {
                        "extracted_assets": [
                            {
                                "asset_id": "SRC_P01_IMG01",
                                "file_path": str(image_path),
                                "page_number": 1,
                                "extraction_method": "embedded_image",
                                "width": 200,
                                "height": 120,
                                "notes": ["pdf_image_name=Im0.png"],
                            }
                        ],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch("app.api.routes.assets._resolve_run_path", return_value=run_path):
                response = self.client.get("/runs/run_test/assets")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["assets"][0]["asset_id"], "SRC_P01_IMG01")
            self.assertTrue(payload["assets"][0]["download_url"].endswith("/runs/run_test/assets/SRC_P01_IMG01"))

    def test_asset_map_endpoint_returns_decision_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "artifacts" / "source").mkdir(parents=True, exist_ok=True)
            (run_path / "artifacts" / "source" / "asset_map.json").write_text(
                json.dumps(
                    {
                        "map": {"FIG_1": "artifacts/source/figures/SRC_P01_IMG01.png"},
                        "entries": [
                            {
                                "artifact_id": "FIG_1",
                                "page_numbers": [1],
                                "candidate_asset_ids": ["SRC_P01_IMG01"],
                                "selected_asset_id": "SRC_P01_IMG01",
                                "resolved_path": "artifacts/source/figures/SRC_P01_IMG01.png",
                                "status": "resolved",
                                "confidence": "high",
                                "decision_reason": "unique_candidate_on_pages",
                                "warnings": [],
                                "matching_signals": {"candidate_count": 1},
                            }
                        ],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            (run_path / "presentation").mkdir(parents=True, exist_ok=True)
            (run_path / "presentation" / "presentation_plan.json").write_text(
                json.dumps({"slides": []}),
                encoding="utf-8",
            )

            with patch("app.api.routes.assets._resolve_run_path", return_value=run_path):
                response = self.client.get("/runs/run_test/asset-map")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["entry_count"], 1)
            self.assertEqual(payload["resolved_count"], 1)
            self.assertEqual(payload["entries"][0]["resolution_status"], "resolved")

    def test_asset_file_endpoint_streams_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            figures_dir = run_path / "artifacts" / "source" / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            image_path = figures_dir / "SRC_P01_IMG01.png"
            image_path.write_bytes(b"png-binary")

            (run_path / "artifacts" / "source" / "extracted_assets.json").write_text(
                json.dumps(
                    {
                        "extracted_assets": [
                            {
                                "asset_id": "SRC_P01_IMG01",
                                "file_path": str(image_path),
                                "page_number": 1,
                                "extraction_method": "embedded_image",
                                "width": 100,
                                "height": 100,
                                "notes": [],
                            }
                        ],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch("app.api.routes.assets._resolve_run_path", return_value=run_path):
                response = self.client.get("/runs/run_test/assets/SRC_P01_IMG01")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"png-binary")


if __name__ == "__main__":
    unittest.main()
