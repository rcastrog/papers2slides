"""Smoke test for ArtifactExtractionAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.artifact_agent import ArtifactExtractionAgent
from app.models.artifact_manifest import ArtifactManifest
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    """Returns deterministic A3 JSON payload for smoke testing."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "artifacts": [
                {
                    "artifact_id": "A_FIG_01",
                    "artifact_label": "Figure 1",
                    "artifact_type": "figure",
                    "page_numbers": [3],
                    "section_id": "S02",
                    "caption": "Model overview.",
                    "nearby_context_summary": "Shows main architecture components.",
                    "file_path": "runs/sample/artifacts/figure_1.png",
                    "extraction_quality": "high",
                    "readability_for_presentation": "high",
                    "core_message": "How inputs flow through modules.",
                    "presentation_value": "high",
                    "recommended_action": "reuse_directly",
                    "recommendation_rationale": "Readable and central to understanding.",
                    "must_preserve_if_adapted": ["component labels", "data flow arrows"],
                    "distortion_risk": "low",
                    "ambiguities": [],
                    "notes": [],
                }
            ],
            "summary": {
                "artifact_count": 1,
                "high_value_artifact_ids": ["A_FIG_01"],
                "high_risk_artifact_ids": [],
                "equation_artifact_ids": [],
                "warnings": [],
            },
        }
        return json.dumps(payload)


class FakeTransportArtifactAlias:
    """Returns deterministic A3 payload with artifact_type alias values."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "artifacts": [
                {
                    "artifact_id": "A_FIG_02",
                    "artifact_label": "Concept Figure",
                    "artifact_type": "conceptual_figure",
                    "page_numbers": [4],
                    "section_id": "S03",
                    "caption": "Concept overview.",
                    "nearby_context_summary": "Depicts conceptual flow.",
                    "file_path": "runs/sample/artifacts/figure_2.png",
                    "extraction_quality": "medium",
                    "readability_for_presentation": "high",
                    "core_message": "Main concept relationships.",
                    "presentation_value": "high",
                    "recommended_action": "reuse_directly",
                    "recommendation_rationale": "Useful explanatory visual.",
                    "must_preserve_if_adapted": ["node labels"],
                    "distortion_risk": "low",
                    "ambiguities": [],
                    "notes": [],
                }
            ],
            "summary": {
                "artifact_count": 1,
                "high_value_artifact_ids": ["A_FIG_02"],
                "high_risk_artifact_ids": [],
                "equation_artifact_ids": [],
                "warnings": [],
            },
        }
        return json.dumps(payload)


class FakeTransportMalformedA2Shape:
    """Returns malformed payload shaped like A2 output to test A3 normalization."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "section_id": "references",
            "section_title": "References",
            "section_role": ["framing_background"],
            "key_claims": [
                {
                    "claim": "Presentation-relevant content exists.",
                    "support_level_within_section": "weak",
                    "notes": "Mocked A2 output.",
                }
            ],
            "summary": "References section raw text",
            "confidence": "low",
        }
        return json.dumps(payload)


class ArtifactExtractionAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_artifact_manifest(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ArtifactExtractionAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "parse_result": {
                "section_index": [{"section_id": "S02", "section_title": "Method"}],
                "pages": ["page-1"],
            }
        }

        result = agent.run(sample_input)

        self.assertIsInstance(result, ArtifactManifest)
        self.assertEqual(result.summary.artifact_count, 1)
        self.assertEqual(result.artifacts[0].artifact_type, "figure")

    def test_run_normalizes_conceptual_figure_artifact_type(self) -> None:
        llm_client = LLMClient(transport=FakeTransportArtifactAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ArtifactExtractionAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "parse_result": {
                "section_index": [{"section_id": "S03", "section_title": "Concepts"}],
                "pages": ["page-2"],
            }
        }

        result = agent.run(sample_input)

        self.assertEqual(result.artifacts[0].artifact_type, "figure")

    def test_run_normalizes_malformed_a2_shaped_payload(self) -> None:
        llm_client = LLMClient(transport=FakeTransportMalformedA2Shape())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ArtifactExtractionAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "parse_result": {
                "section_index": [{"section_id": "references", "section_title": "References"}],
                "pages": ["page-3"],
            }
        }

        result = agent.run(sample_input)

        self.assertIsInstance(result, ArtifactManifest)
        self.assertEqual(result.artifacts, [])
        self.assertEqual(result.summary.artifact_count, 0)
        self.assertTrue(any("normalized" in warning.lower() for warning in result.summary.warnings))


if __name__ == "__main__":
    unittest.main()
