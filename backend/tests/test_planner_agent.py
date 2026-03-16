"""Smoke test for PresentationPlannerAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.planner_agent import PresentationPlannerAgent
from app.models.presentation_plan import PresentationPlan
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    """Returns deterministic A6 JSON payload for smoke testing."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "deck_metadata": {
                "title": "Test Deck",
                "subtitle": "Auto plan",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Problem to conclusion.",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Test Deck",
                    "objective": "Introduce context.",
                    "key_points": ["What", "Why"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "text_only",
                            "asset_id": "none",
                            "source_origin": "none",
                            "usage_mode": "none",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Simple opening slide.",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "From introduction.",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source paper",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": ["Open with motivation."],
                    "confidence_notes": [],
                    "layout_hint": "title and bullets",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportNullVisualAsset:
    """Returns deterministic A6 payload with a null visual asset_id."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "deck_metadata": {
                "title": "Test Deck",
                "subtitle": "Auto plan",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Problem to conclusion.",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Test Deck",
                    "objective": "Introduce context.",
                    "key_points": ["What", "Why"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "text_only",
                            "asset_id": None,
                            "source_origin": "none",
                            "usage_mode": "none",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Simple opening slide.",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "From introduction.",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source paper",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": ["Open with motivation."],
                    "confidence_notes": [],
                    "layout_hint": "title and bullets",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportUsageModeAlias:
    """Returns deterministic A6 payload with usage_mode alias from artifact actions."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "deck_metadata": {
                "title": "Test Deck",
                "subtitle": "Auto plan",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Problem to conclusion.",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Test Deck",
                    "objective": "Introduce context.",
                    "key_points": ["What", "Why"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "source_figure",
                            "asset_id": "A_FIG_01",
                            "source_origin": "source_paper",
                            "usage_mode": "crop_or_clean",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Focus on key region.",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "From introduction.",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source paper",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": ["Open with motivation."],
                    "confidence_notes": [],
                    "layout_hint": "title and bullets",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportSupportTypeAlias:
    """Returns deterministic A6 payload with support_type alias values."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "deck_metadata": {
                "title": "Test Deck",
                "subtitle": "Auto plan",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Problem to conclusion.",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Test Deck",
                    "objective": "Introduce context.",
                    "key_points": ["What", "Why"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "text_only",
                            "asset_id": "none",
                            "source_origin": "none",
                            "usage_mode": "none",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Simple opening slide.",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_metadata",
                            "support_id": "meta1",
                            "support_note": "From metadata context.",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source paper",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": ["Open with motivation."],
                    "confidence_notes": [],
                    "layout_hint": "title and bullets",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
        return json.dumps(payload)


class FakeTransportVisualTypeAlias:
    """Returns deterministic A6 payload with visual_type alias values."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "deck_metadata": {
                "title": "Test Deck",
                "subtitle": "Auto plan",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Problem to conclusion.",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Test Deck",
                    "objective": "Introduce context.",
                    "key_points": ["What", "Why"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "source_plot",
                            "asset_id": "A_PLOT_01",
                            "source_origin": "source_paper",
                            "usage_mode": "reuse",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Shows trend clearly.",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "From introduction.",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source paper",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": ["Open with motivation."],
                    "confidence_notes": [],
                    "layout_hint": "title and bullets",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
        return json.dumps(payload)


class PlannerAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_presentation_plan(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PresentationPlannerAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"job_spec": {"job_id": "job-1"}})

        self.assertIsInstance(result, PresentationPlan)
        self.assertEqual(len(result.slides), 1)

    def test_run_coerces_null_visual_asset_id(self) -> None:
        llm_client = LLMClient(transport=FakeTransportNullVisualAsset())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PresentationPlannerAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"job_spec": {"job_id": "job-1"}})

        self.assertIsInstance(result, PresentationPlan)
        self.assertEqual(result.slides[0].visuals[0].asset_id, "none")

    def test_run_normalizes_usage_mode_alias(self) -> None:
        llm_client = LLMClient(transport=FakeTransportUsageModeAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PresentationPlannerAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"job_spec": {"job_id": "job-1"}})

        self.assertEqual(result.slides[0].visuals[0].usage_mode, "adapted")

    def test_run_normalizes_support_type_alias(self) -> None:
        llm_client = LLMClient(transport=FakeTransportSupportTypeAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PresentationPlannerAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"job_spec": {"job_id": "job-1"}})

        self.assertEqual(result.slides[0].source_support[0].support_type, "source_section")

    def test_run_normalizes_visual_type_alias(self) -> None:
        llm_client = LLMClient(transport=FakeTransportVisualTypeAlias())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PresentationPlannerAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"job_spec": {"job_id": "job-1"}})

        self.assertEqual(result.slides[0].visuals[0].visual_type, "source_chart")


if __name__ == "__main__":
    unittest.main()
