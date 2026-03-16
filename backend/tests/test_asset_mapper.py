"""Unit tests for conservative source asset mapping logic."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.artifact_manifest import ArtifactManifest
from app.services.asset_mapper import AssetMapper
from app.services.pdf_artifact_extractor import ExtractedArtifactBundle, ExtractedAsset


def _build_manifest(
    page_numbers: list[int],
    artifact_id: str = "FIG_1",
    artifact_label: str = "Figure 1",
    caption: str = "caption",
) -> ArtifactManifest:
    return ArtifactManifest.model_validate(
        {
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "artifact_label": artifact_label,
                    "artifact_type": "figure",
                    "page_numbers": page_numbers,
                    "section_id": "s1",
                    "caption": caption,
                    "nearby_context_summary": "context",
                    "file_path": "",
                    "extraction_quality": "high",
                    "readability_for_presentation": "high",
                    "core_message": "message",
                    "presentation_value": "high",
                    "recommended_action": "reuse_directly",
                    "recommendation_rationale": "clear",
                    "must_preserve_if_adapted": [],
                    "distortion_risk": "low",
                    "ambiguities": [],
                    "notes": [],
                }
            ],
            "summary": {
                "artifact_count": 1,
                "high_value_artifact_ids": [artifact_id],
                "high_risk_artifact_ids": [],
                "equation_artifact_ids": [],
                "warnings": [],
            },
        }
    )


class AssetMapperTest(unittest.TestCase):
    def test_build_asset_map_resolves_unique_page_match(self) -> None:
        mapper = AssetMapper()
        manifest = _build_manifest(page_numbers=[2])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "SRC_P02_IMG01.png"
            path.write_bytes(b"x")
            extracted = ExtractedArtifactBundle(
                extracted_assets=[
                    ExtractedAsset(
                        asset_id="SRC_P02_IMG01",
                        file_path=str(path),
                        page_number=2,
                        extraction_method="embedded_image",
                        width=100,
                        height=100,
                        notes=[],
                    )
                ],
                warnings=[],
            )

            result = mapper.build_asset_map(artifact_manifest=manifest, extracted_assets=extracted)

        self.assertEqual(result.map.get("FIG_1"), str(path.resolve()))
        self.assertTrue(any(entry.status == "resolved" for entry in result.entries))
        self.assertTrue(any(entry.decision_reason == "unique_candidate_on_pages" for entry in result.entries))

    def test_build_asset_map_marks_ambiguous_unresolved(self) -> None:
        mapper = AssetMapper()
        manifest = _build_manifest(
            page_numbers=[3],
            artifact_id="ARTIFACT_X",
            artifact_label="Chart",
            caption="Summary panel",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "SRC_P03_IMG01.png"
            second = Path(tmpdir) / "SRC_P03_IMG02.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")

            extracted = ExtractedArtifactBundle(
                extracted_assets=[
                    ExtractedAsset(
                        asset_id="SRC_P03_IMG01",
                        file_path=str(first),
                        page_number=3,
                        extraction_method="embedded_image",
                        width=100,
                        height=100,
                        notes=[],
                    ),
                    ExtractedAsset(
                        asset_id="SRC_P03_IMG02",
                        file_path=str(second),
                        page_number=3,
                        extraction_method="embedded_image",
                        width=100,
                        height=100,
                        notes=[],
                    ),
                ],
                warnings=[],
            )

            result = mapper.build_asset_map(artifact_manifest=manifest, extracted_assets=extracted)

        self.assertNotIn("ARTIFACT_X", result.map)
        self.assertTrue(any(entry.status == "ambiguous" for entry in result.entries))
        self.assertTrue(any(entry.confidence == "ambiguous" for entry in result.entries))
        self.assertTrue(any("multiple_candidates_without_strong_signal" in warning for warning in result.warnings))

    def test_build_asset_map_resolves_by_figure_hint_when_unique(self) -> None:
        mapper = AssetMapper()
        manifest = _build_manifest(
            page_numbers=[5],
            artifact_id="FIG_5",
            artifact_label="Figure 2",
            caption="Figure 2: policy response",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "SRC_P05_IMG01.png"
            second = Path(tmpdir) / "SRC_P05_IMG02.png"
            first.write_bytes(b"1")
            second.write_bytes(b"2")

            extracted = ExtractedArtifactBundle(
                extracted_assets=[
                    ExtractedAsset(
                        asset_id="SRC_P05_IMG01",
                        file_path=str(first),
                        page_number=5,
                        extraction_method="embedded_image",
                        width=100,
                        height=100,
                        notes=[],
                    ),
                    ExtractedAsset(
                        asset_id="SRC_P05_IMG02",
                        file_path=str(second),
                        page_number=5,
                        extraction_method="embedded_image",
                        width=100,
                        height=100,
                        notes=[],
                    ),
                ],
                warnings=[],
            )

            result = mapper.build_asset_map(artifact_manifest=manifest, extracted_assets=extracted)

        self.assertEqual(result.map.get("FIG_5"), str(second.resolve()))
        self.assertTrue(any(entry.decision_reason == "figure_hint_unique_match" for entry in result.entries))


if __name__ == "__main__":
    unittest.main()
