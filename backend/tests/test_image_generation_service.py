"""Tests for OpenAI conceptual image generation service."""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.generated_visuals import GeneratedVisualEntry
from app.services.image_generation_service import (
    ImageGenerationSettings,
    OpenAIConceptualImageGenerator,
    _build_postprocessed_prompt,
)


class _FakeImagesAPI:
    def __init__(self, payload_b64: str) -> None:
        self._payload_b64 = payload_b64
        self.calls = 0

    def generate(self, **kwargs):
        _ = kwargs
        self.calls += 1
        return SimpleNamespace(data=[SimpleNamespace(b64_json=self._payload_b64)])


class _FakeClient:
    def __init__(self, payload_b64: str) -> None:
        self.images = _FakeImagesAPI(payload_b64)


def _entry(visual_id: str = "GV01") -> GeneratedVisualEntry:
    return GeneratedVisualEntry.model_validate(
        {
            "visual_id": visual_id,
            "slide_number": 1,
            "slide_title": "Why Study AI's Labor Market Impacts?",
            "visual_purpose": "Explain central mechanism.",
            "visual_kind": "concept_map",
            "status": "recommended",
            "conceptual_basis": {
                "grounded_in_source_sections": ["s1"],
                "grounded_in_source_artifacts": [],
                "grounded_in_reference_ids": ["R001"],
            },
            "provenance_label": "conceptual",
            "must_preserve_if_adapted": [],
            "visual_spec": {
                "composition": "A central node and two branches",
                "main_elements": [
                    "Central node: 'Observed Exposure'",
                    "Branch 1: 'Theoretical Capabilities' with details",
                    "Branch 2: 'Observed Usage' with details",
                ],
                "labels_or_text": [
                    "Central node: 'Observed Exposure'",
                    "Branch 1: 'Theoretical Capabilities'",
                    "Branch 2: 'Observed Usage'",
                ],
                "style_notes": ["Use clean spacing", "Avoid clutter"],
                "language": "en",
            },
            "safety_notes": ["conceptual only"],
            "image_generation_prompt": "raw prompt",
        }
    )


class ImageGenerationServiceTests(unittest.TestCase):
    def test_postprocessed_prompt_strips_verbose_suffixes(self) -> None:
        prompt = _build_postprocessed_prompt(_entry())
        self.assertIn("Observed Exposure", prompt)
        self.assertNotIn("with details", prompt)

    def test_materialize_generates_png_and_uses_cache(self) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\nFAKE"
        payload_b64 = base64.b64encode(png_bytes).decode("ascii")

        settings = ImageGenerationSettings(enabled=True, max_images_per_run=4, max_retries_per_image=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "cache"
            output_dir = root / "assets"
            generator = OpenAIConceptualImageGenerator(api_key="k", settings=settings, cache_dir=cache_dir)

            fake_client = _FakeClient(payload_b64)
            with patch.object(OpenAIConceptualImageGenerator, "_build_openai_client", return_value=fake_client):
                resolved_first, warnings_first = generator.materialize(entries=[_entry("GV01")], run_assets_dir=output_dir)
                resolved_second, warnings_second = generator.materialize(entries=[_entry("GV01")], run_assets_dir=output_dir)

            self.assertFalse(warnings_first)
            self.assertFalse(warnings_second)
            self.assertIn("GV01", resolved_first)
            self.assertIn("GV01", resolved_second)
            self.assertTrue((output_dir / "GV01.png").is_file())
            self.assertEqual((output_dir / "GV01.png").read_bytes(), png_bytes)
            self.assertEqual(fake_client.images.calls, 1)

    def test_materialize_respects_cap(self) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\nFAKE"
        payload_b64 = base64.b64encode(png_bytes).decode("ascii")

        settings = ImageGenerationSettings(enabled=True, max_images_per_run=1, max_retries_per_image=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generator = OpenAIConceptualImageGenerator(api_key="k", settings=settings, cache_dir=root / "cache")
            fake_client = _FakeClient(payload_b64)
            with patch.object(OpenAIConceptualImageGenerator, "_build_openai_client", return_value=fake_client):
                resolved, warnings = generator.materialize(entries=[_entry("GV01"), _entry("GV02")], run_assets_dir=root / "assets")

            self.assertEqual(len(resolved), 1)
            self.assertEqual(fake_client.images.calls, 1)
            self.assertTrue(any("capped" in warning.lower() for warning in warnings))


if __name__ == "__main__":
    unittest.main()
