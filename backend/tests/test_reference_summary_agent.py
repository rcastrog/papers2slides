"""Smoke test for ReferenceSummaryAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.reference_summary_agent import ReferenceSummaryAgent
from app.models.reference_summary import ReferenceSummary
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    """Returns deterministic A5 JSON payload for smoke testing."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "reference_id": "R001",
            "reference_title": "Test Reference",
            "summary": {
                "main_topic": "Benchmarking",
                "main_contribution": "Introduces a comparison baseline.",
                "brief_summary": "Useful context for comparing methods.",
            },
            "relation_to_source_paper": {
                "relation_type": ["comparison_baseline_interpretation"],
                "description": "Helps interpret source-paper results.",
                "importance_for_source_presentation": "medium",
            },
            "useful_points_for_main_presentation": [
                {
                    "point": "Provides baseline setup",
                    "usage_type": "comparison",
                    "support_strength": "moderate",
                }
            ],
            "possible_useful_artifacts": [],
            "mention_recommendation": {
                "should_mention_in_final_deck": True,
                "recommended_scope": "passing_mention",
                "rationale": "Adds concise context.",
            },
            "warnings": [],
            "confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportRelationAlias:
    """Returns deterministic A5 payload using slash alias relation type."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "reference_id": "R002",
            "reference_title": "Alias Reference",
            "summary": {
                "main_topic": "Comparison",
                "main_contribution": "Helps baseline interpretation.",
                "brief_summary": "Provides comparative context.",
            },
            "relation_to_source_paper": {
                "relation_type": ["comparison/baseline_interpretation"],
                "description": "Maps to canonical relation type.",
                "importance_for_source_presentation": "medium",
            },
            "useful_points_for_main_presentation": [],
            "possible_useful_artifacts": [],
            "mention_recommendation": {
                "should_mention_in_final_deck": True,
                "recommended_scope": "passing_mention",
                "rationale": "Useful supporting context.",
            },
            "warnings": [],
            "confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportArtifactTypeCombo:
    """Returns deterministic A5 payload with combined artifact type value."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "reference_id": "R003",
            "reference_title": "Artifact Combo Reference",
            "summary": {
                "main_topic": "Visualization",
                "main_contribution": "Provides helpful visual evidence.",
                "brief_summary": "Contains visual artifacts for context.",
            },
            "relation_to_source_paper": {
                "relation_type": ["supporting_evidence"],
                "description": "Supports interpretation of source findings.",
                "importance_for_source_presentation": "medium",
            },
            "useful_points_for_main_presentation": [],
            "possible_useful_artifacts": [
                {
                    "artifact_hint": "Main comparison figure/table",
                    "artifact_type": "figure | table",
                    "why_it_might_help": "Summarizes the comparison clearly.",
                }
            ],
            "mention_recommendation": {
                "should_mention_in_final_deck": True,
                "recommended_scope": "passing_mention",
                "rationale": "Useful concise context.",
            },
            "warnings": [],
            "confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportEmptyRelationType:
    """Returns deterministic A5 payload with empty relation_type list."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "reference_id": "R004",
            "reference_title": "Empty Relation Type Reference",
            "summary": {
                "main_topic": "Background",
                "main_contribution": "Provides context.",
                "brief_summary": "A contextual reference.",
            },
            "relation_to_source_paper": {
                "relation_type": [],
                "description": "General context for the source paper.",
                "importance_for_source_presentation": "low",
            },
            "useful_points_for_main_presentation": [],
            "possible_useful_artifacts": [],
            "mention_recommendation": {
                "should_mention_in_final_deck": False,
                "recommended_scope": "none",
                "rationale": "Not central.",
            },
            "warnings": [],
            "confidence": "low",
        }
        return json.dumps(payload)


class ReferenceSummaryAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_reference_summary(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ReferenceSummaryAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"reference_id": "R001"})

        self.assertIsInstance(result, ReferenceSummary)
        self.assertEqual(result.reference_id, "R001")

    def test_run_normalizes_relation_type_aliases(self) -> None:
        llm_client = LLMClient(transport=FakeTransportRelationAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ReferenceSummaryAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"reference_id": "R002"})

        self.assertEqual(
            result.relation_to_source_paper.relation_type,
            ["comparison_baseline_interpretation"],
        )

    def test_run_normalizes_combined_artifact_type(self) -> None:
        llm_client = LLMClient(transport=FakeTransportArtifactTypeCombo())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ReferenceSummaryAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"reference_id": "R003"})

        self.assertEqual(result.possible_useful_artifacts[0].artifact_type, "figure")

    def test_run_falls_back_for_empty_relation_type(self) -> None:
        llm_client = LLMClient(transport=FakeTransportEmptyRelationType())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ReferenceSummaryAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"reference_id": "R004"})

        self.assertEqual(result.relation_to_source_paper.relation_type, ["background_context"])


if __name__ == "__main__":
    unittest.main()
