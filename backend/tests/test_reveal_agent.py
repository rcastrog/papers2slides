"""Smoke tests for RevealBuilderAgent and RevealRenderer."""

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

from app.agents.reveal_agent import RevealBuilderAgent
from app.models.generated_visuals import GeneratedVisuals
from app.models.presentation_plan import PresentationPlan
from app.models.reveal_result import RevealRenderResult
from app.models.speaker_notes import SpeakerNotes
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "render_status": "success",
                "output": {
                    "reveal_root_path": "presentation/reveal",
                    "entry_html_path": "presentation/reveal/index.html",
                    "assets_directory": "presentation/reveal/assets",
                    "theme_name": "minimal-v1",
                },
                "slide_render_results": [
                    {
                        "slide_number": 1,
                        "title": "Slide 1",
                        "status": "rendered",
                        "assets_used": [],
                        "citations_rendered": ["Source"],
                        "notes_attached": True,
                        "warnings": [],
                    }
                ],
                "global_warnings": [],
                "deviations": [],
            }
        )


def _build_minimal_plan() -> PresentationPlan:
    return PresentationPlan.model_validate(
        {
            "deck_metadata": {
                "title": "Test Deck",
                "subtitle": "Sub",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Story",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Slide 1",
                    "objective": "Obj",
                    "key_points": ["A", "B"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "text_only",
                            "asset_id": "none",
                            "source_origin": "none",
                            "usage_mode": "none",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Simple",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "note",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
    )


def _build_visual_plan() -> PresentationPlan:
    return PresentationPlan.model_validate(
        {
            "deck_metadata": {
                "title": "Visual Deck",
                "subtitle": "Sub",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Story",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "method",
                    "title": "Method Slide",
                    "objective": "Obj",
                    "key_points": ["A", "B"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "source_figure",
                            "asset_id": "A_FIG_01",
                            "source_origin": "source_paper",
                            "usage_mode": "reuse",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Core figure from source paper.",
                        },
                        {
                            "visual_type": "generated_conceptual",
                            "asset_id": "GV01",
                            "source_origin": "generated",
                            "usage_mode": "conceptual",
                            "placement_hint": "left_visual_right_text",
                            "why_this_visual": "Conceptual support visual.",
                        },
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "note",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
    )


def _build_source_visual_only_plan() -> PresentationPlan:
    return PresentationPlan.model_validate(
        {
            "deck_metadata": {
                "title": "Source Visual Deck",
                "subtitle": "Sub",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "research_specialists",
                "target_duration_minutes": 20,
                "target_slide_count": 12,
            },
            "narrative_arc": {
                "overall_story": "Story",
                "audience_adaptation_notes": [],
                "language_adaptation_notes": [],
            },
            "slides": [
                {
                    "slide_number": 1,
                    "slide_role": "method",
                    "title": "Method Slide",
                    "objective": "Obj",
                    "key_points": ["A", "B"],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "source_figure",
                            "asset_id": "A_FIG_01",
                            "source_origin": "source_paper",
                            "usage_mode": "reuse",
                            "placement_hint": "center_focus",
                            "why_this_visual": "Core figure from source paper.",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_section",
                            "support_id": "s1",
                            "support_note": "note",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source",
                            "source_kind": "source_paper",
                        }
                    ],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
    )


def _build_minimal_notes() -> SpeakerNotes:
    return SpeakerNotes.model_validate(
        {
            "deck_language": "en",
            "notes_style": "brief_talking_points",
            "slide_notes": [
                {
                    "slide_number": 1,
                    "slide_title": "Slide 1",
                    "talking_points": ["Talk A"],
                    "timing_hint_seconds": 60,
                    "caution_notes": [],
                }
            ],
            "global_notes_warnings": [],
        }
    )


def _build_minimal_visuals() -> GeneratedVisuals:
    return GeneratedVisuals.model_validate(
        {
            "generated_visuals": [],
            "global_visual_warnings": [],
        }
    )


def _build_visuals_with_generated_asset() -> GeneratedVisuals:
    return GeneratedVisuals.model_validate(
        {
            "generated_visuals": [
                {
                    "visual_id": "GV01",
                    "slide_number": 1,
                    "slide_title": "Method Slide",
                    "visual_purpose": "Show conceptual flow",
                    "visual_kind": "workflow",
                    "status": "recommended",
                    "conceptual_basis": {
                        "grounded_in_source_sections": ["s1"],
                        "grounded_in_source_artifacts": [],
                        "grounded_in_reference_ids": [],
                    },
                    "provenance_label": "conceptual",
                    "must_preserve_if_adapted": [],
                    "visual_spec": {
                        "composition": "Simple flow",
                        "main_elements": ["Input", "Model", "Output"],
                        "labels_or_text": ["Flow"],
                        "style_notes": ["Clean"],
                        "language": "en",
                    },
                    "safety_notes": ["Conceptual only"],
                    "image_generation_prompt": "Flow diagram",
                }
            ],
            "global_visual_warnings": [],
        }
    )


class RevealAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_reveal_result(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = RevealBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})
        self.assertIsInstance(result, RevealRenderResult)

    def test_renderer_creates_index_html(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = RevealBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "reveal"
            render_result = agent.render(
                presentation_plan=_build_minimal_plan(),
                speaker_notes=_build_minimal_notes(),
                generated_visuals=_build_minimal_visuals(),
                output_dir=output_dir,
                asset_map={},
            )

            self.assertTrue((output_dir / "index.html").is_file())
            html_content = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Slide 1", html_content)
            self.assertEqual(render_result.render_status, "success")

    def test_renderer_renders_visual_frames_with_generated_fallback(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = RevealBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "presentation" / "reveal"
            render_result = agent.render(
                presentation_plan=_build_visual_plan(),
                speaker_notes=_build_minimal_notes(),
                generated_visuals=_build_visuals_with_generated_asset(),
                output_dir=output_dir,
                asset_map={},
            )

            html_content = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("visual-frame", html_content)
            self.assertIn("assets/GV01.svg", html_content)
            self.assertIn("conceptual AI-generated", html_content)
            self.assertNotIn("conceptual-ai-tag", html_content)

            first_slide = render_result.slide_render_results[0]
            self.assertEqual(first_slide.status, "rendered_with_warning")
            self.assertTrue(any("A_FIG_01" in warning for warning in first_slide.warnings))

    def test_renderer_uses_asset_map_for_source_visual(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = RevealBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDAT"
            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00"
            b"\x00\x00\x00IEND\xaeB`\x82"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            output_dir = temp_dir / "presentation" / "reveal"
            source_asset = temp_dir / "source.png"
            source_asset.write_bytes(png_bytes)

            render_result = agent.render(
                presentation_plan=_build_source_visual_only_plan(),
                speaker_notes=_build_minimal_notes(),
                generated_visuals=_build_minimal_visuals(),
                output_dir=output_dir,
                asset_map={"A_FIG_01": str(source_asset)},
            )

            html_content = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("assets/source.png", html_content)

            first_slide = render_result.slide_render_results[0]
            self.assertEqual(first_slide.status, "rendered")
            self.assertEqual(first_slide.assets_used[0].resolved_path, str(source_asset))
            self.assertEqual(first_slide.warnings, [])

    def test_renderer_outputs_citation_purpose_explainability(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = RevealBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Citation Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": 12,
                },
                "narrative_arc": {
                    "overall_story": "Story",
                    "audience_adaptation_notes": [],
                    "language_adaptation_notes": [],
                },
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_role": "result",
                        "title": "Results",
                        "objective": "Obj",
                        "key_points": ["A"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "text_only",
                                "asset_id": "none",
                                "source_origin": "none",
                                "usage_mode": "none",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Simple",
                            }
                        ],
                        "source_support": [],
                        "citations": [
                            {
                                "short_citation": "Alpha et al., 2024",
                                "source_kind": "reference_paper",
                                "citation_purpose": "source_of_claim",
                            },
                            {
                                "short_citation": "Beta et al., 2022",
                                "source_kind": "reference_paper",
                                "citation_purpose": "method_background",
                            },
                        ],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    }
                ],
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "reveal"
            agent.render(
                presentation_plan=plan,
                speaker_notes=_build_minimal_notes(),
                generated_visuals=_build_minimal_visuals(),
                output_dir=output_dir,
                asset_map={},
            )

            html_content = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("citation-chip", html_content)
            self.assertIn("Why cited", html_content)
            self.assertIn("supports the claim that Obj", html_content)
            self.assertIn("provides method background for Obj", html_content)


if __name__ == "__main__":
    unittest.main()
