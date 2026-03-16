"""Smoke test for VisualGenerationAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.visual_agent import VisualGenerationAgent
from app.models.generated_visuals import GeneratedVisuals
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "generated_visuals": [
                    {
                        "visual_id": "GV01",
                        "slide_number": 1,
                        "slide_title": "Slide 1",
                        "visual_purpose": "Explain context",
                        "visual_kind": "concept_map",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s1"],
                            "grounded_in_source_artifacts": [],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Single diagram",
                            "main_elements": ["Context"],
                            "labels_or_text": ["Context"],
                            "style_notes": ["Simple"],
                            "language": "en",
                        },
                        "safety_notes": [],
                        "image_generation_prompt": "A simple concept map",
                    }
                ],
                "global_visual_warnings": [],
            }
        )


class FakeTransportVisualKindAlias:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "generated_visuals": [
                    {
                        "visual_id": "GV02",
                        "slide_number": 2,
                        "slide_title": "Slide 2",
                        "visual_purpose": "Explain workflow",
                        "visual_kind": "flowchart",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s2"],
                            "grounded_in_source_artifacts": [],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Stepwise blocks",
                            "main_elements": ["Step A", "Step B"],
                            "labels_or_text": ["A", "B"],
                            "style_notes": ["Clean arrows"],
                            "language": "en",
                        },
                        "safety_notes": [],
                        "image_generation_prompt": "A simple flowchart",
                    }
                ],
                "global_visual_warnings": [],
            }
        )


class FakeTransportVisualKindDemographicAlias:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "generated_visuals": [
                    {
                        "visual_id": "GV03",
                        "slide_number": 3,
                        "slide_title": "Slide 3",
                        "visual_purpose": "Compare exposure groups",
                        "visual_kind": "demographic_breakdown_chart",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s3"],
                            "grounded_in_source_artifacts": [],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Grouped bars",
                            "main_elements": ["Group A", "Group B"],
                            "labels_or_text": ["A", "B"],
                            "style_notes": ["Simple"],
                            "language": "en",
                        },
                        "safety_notes": [],
                        "image_generation_prompt": "A grouped comparison chart",
                    }
                ],
                "global_visual_warnings": [],
            }
        )


class FakeTransportVisualKindUnknown:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "generated_visuals": [
                    {
                        "visual_id": "GV04",
                        "slide_number": 4,
                        "slide_title": "Slide 4",
                        "visual_purpose": "General explanation",
                        "visual_kind": "radial_story_map",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s4"],
                            "grounded_in_source_artifacts": [],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Hub and spokes",
                            "main_elements": ["Center", "Spoke"],
                            "labels_or_text": ["Center", "Spoke"],
                            "style_notes": ["Simple"],
                            "language": "en",
                        },
                        "safety_notes": [],
                        "image_generation_prompt": "A conceptual radial map",
                    }
                ],
                "global_visual_warnings": [],
            }
        )


class VisualAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_generated_visuals(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = VisualGenerationAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertIsInstance(result, GeneratedVisuals)
        self.assertEqual(result.generated_visuals[0].visual_id, "GV01")

    def test_run_normalizes_flowchart_visual_kind(self) -> None:
        llm_client = LLMClient(transport=FakeTransportVisualKindAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = VisualGenerationAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertEqual(result.generated_visuals[0].visual_kind, "workflow")

    def test_run_normalizes_demographic_breakdown_chart_to_comparison_framework(self) -> None:
        llm_client = LLMClient(transport=FakeTransportVisualKindDemographicAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = VisualGenerationAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertEqual(result.generated_visuals[0].visual_kind, "comparison_framework")

    def test_run_falls_back_unknown_visual_kind_to_other(self) -> None:
        llm_client = LLMClient(transport=FakeTransportVisualKindUnknown())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = VisualGenerationAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertEqual(result.generated_visuals[0].visual_kind, "other")


if __name__ == "__main__":
    unittest.main()
