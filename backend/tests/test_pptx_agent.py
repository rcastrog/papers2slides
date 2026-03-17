"""Smoke tests for PPTXBuilderAgent and PPTXRenderer."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.pptx_agent import PPTXBuilderAgent
from app.models.generated_visuals import GeneratedVisuals
from app.models.pptx_result import PPTXBuildResult
from app.models.presentation_plan import PresentationPlan
from app.models.speaker_notes import SpeakerNotes
from app.renderers.pptx_renderer import PPTXRenderer
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class _FakeParagraph:
    def __init__(self) -> None:
        self.text = ""
        self.font = type("_FakeFont", (), {"size": None})()


class _FakeTextFrame:
    def __init__(self) -> None:
        self.paragraphs = [_FakeParagraph()]
        self.text = ""
        self.word_wrap = False

    def clear(self) -> None:
        self.paragraphs = [_FakeParagraph()]

    def add_paragraph(self) -> _FakeParagraph:
        paragraph = _FakeParagraph()
        self.paragraphs.append(paragraph)
        return paragraph


class _FakeTitleShape:
    def __init__(self) -> None:
        self.text = ""


class _FakePlaceholderShape:
    def __init__(self) -> None:
        self.text_frame = _FakeTextFrame()


class _FakeTextboxShape:
    def __init__(self) -> None:
        self.text_frame = _FakeTextFrame()


class _FakeShapes:
    def __init__(self) -> None:
        self.title = _FakeTitleShape()
        self.placeholders = [None, _FakePlaceholderShape()]
        self._pictures: list[str] = []

    def add_textbox(self, left: int, top: int, width: int, height: int) -> _FakeTextboxShape:
        _ = (left, top, width, height)
        return _FakeTextboxShape()

    def add_picture(self, image_path: str, left: int, top: int, width: int | None = None, height: int | None = None) -> None:
        _ = (left, top, width, height)
        self._pictures.append(image_path)


class _FakeNotesFrame:
    def __init__(self) -> None:
        self.text = ""


class _FakeNotesSlide:
    def __init__(self) -> None:
        self.notes_text_frame = _FakeNotesFrame()


class _FakeSlide:
    def __init__(self) -> None:
        self.shapes = _FakeShapes()
        self.notes_slide = _FakeNotesSlide()


class _FakeSlides:
    def __init__(self) -> None:
        self._slides: list[_FakeSlide] = []

    def add_slide(self, layout: object) -> _FakeSlide:
        _ = layout
        slide = _FakeSlide()
        self._slides.append(slide)
        return slide


class _FakePresentation:
    def __init__(self) -> None:
        self.slide_layouts = [object(), object()]
        self.slides = _FakeSlides()

    def save(self, output_path: str) -> None:
        Path(output_path).write_bytes(b"fake-pptx")


class _FakePptxModule:
    Presentation = _FakePresentation


class _FakePptxModuleWithFile:
    __file__ = "C:/fake/site-packages/pptx/__init__.py"
    Presentation = _FakePresentation


class FakeTransport:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "build_status": "success",
                "output": {
                    "pptx_path": "presentation/pptx/deck.pptx",
                    "template_used": "default",
                    "notes_insertion_supported": True,
                },
                "slide_build_results": [
                    {
                        "slide_number": 1,
                        "title": "Slide 1",
                        "status": "built",
                        "assets_used": [],
                        "notes_inserted": True,
                        "citations_inserted": True,
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


def _build_plan_with_source_visual(asset_id: str) -> PresentationPlan:
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
                    "slide_role": "contribution",
                    "title": "Slide 1",
                    "objective": "Obj",
                    "key_points": [
                        "Point A",
                        "Point B",
                        "Point C",
                        "Point D",
                        "Point E",
                        "Point F",
                    ],
                    "must_avoid": [],
                    "visuals": [
                        {
                            "visual_type": "source_figure",
                            "asset_id": asset_id,
                            "source_origin": "source_paper",
                            "usage_mode": "reuse",
                            "placement_hint": "left_visual_right_text",
                            "why_this_visual": "Use source figure",
                        }
                    ],
                    "source_support": [
                        {
                            "support_type": "source_artifact",
                            "support_id": asset_id,
                            "support_note": "source",
                        }
                    ],
                    "citations": [
                        {
                            "short_citation": "Source A",
                            "source_kind": "source_paper",
                        },
                        {
                            "short_citation": "Source B",
                            "source_kind": "reference_paper",
                        },
                    ],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "left_visual_right_text",
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


def _build_visuals_with_source_artifact(artifact_id: str) -> GeneratedVisuals:
    return GeneratedVisuals.model_validate(
        {
            "generated_visuals": [
                {
                    "visual_id": "VIS_1",
                    "slide_number": 1,
                    "slide_title": "Slide 1",
                    "visual_purpose": "Show source figure",
                    "visual_kind": "other",
                    "status": "recommended",
                    "conceptual_basis": {
                        "grounded_in_source_sections": ["s1"],
                        "grounded_in_source_artifacts": [artifact_id],
                        "grounded_in_reference_ids": [],
                    },
                    "provenance_label": "adapted_from_source",
                    "must_preserve_if_adapted": [],
                    "visual_spec": {
                        "composition": "single",
                        "main_elements": ["figure"],
                        "labels_or_text": [],
                        "style_notes": [],
                        "language": "en",
                    },
                    "safety_notes": [],
                    "image_generation_prompt": "",
                }
            ],
            "global_visual_warnings": [],
        }
    )


def _build_conceptual_visuals() -> GeneratedVisuals:
    return GeneratedVisuals.model_validate(
        {
            "generated_visuals": [
                {
                    "visual_id": "GV01",
                    "slide_number": 1,
                    "slide_title": "Slide 1",
                    "visual_purpose": "Explain mechanism",
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
                        "composition": "left to right flow",
                        "main_elements": ["Input", "Model", "Output"],
                        "labels_or_text": ["Context"],
                        "style_notes": ["clean"],
                        "language": "en",
                    },
                    "safety_notes": [],
                    "image_generation_prompt": "",
                }
            ],
            "global_visual_warnings": [],
        }
    )


class PPTXAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_pptx_result(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PPTXBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})
        self.assertIsInstance(result, PPTXBuildResult)

    def test_renderer_creates_pptx_file(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PPTXBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "deck.pptx"
            with patch("app.renderers.pptx_renderer.importlib.import_module", return_value=_FakePptxModule()):
                build_result = agent.build(
                    presentation_plan=_build_minimal_plan(),
                    speaker_notes=_build_minimal_notes(),
                    generated_visuals=_build_minimal_visuals(),
                    output_path=output_path,
                    asset_map={},
                )

            self.assertTrue(output_path.is_file())
            self.assertEqual(build_result.build_status, "success")

    def test_renderer_uses_mapped_source_asset(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PPTXBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDAT"
            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00"
            b"\x00\x00\x00IEND\xaeB`\x82"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            output_path = temp_dir / "deck.pptx"
            source_asset = temp_dir / "source.png"
            source_asset.write_bytes(png_bytes)

            with patch("app.renderers.pptx_renderer.importlib.import_module", return_value=_FakePptxModule()):
                build_result = agent.build(
                    presentation_plan=_build_minimal_plan(),
                    speaker_notes=_build_minimal_notes(),
                    generated_visuals=_build_visuals_with_source_artifact("FIG_1"),
                    output_path=output_path,
                    asset_map={"FIG_1": str(source_asset)},
                )

            self.assertTrue(output_path.is_file())
            self.assertEqual(build_result.build_status, "success")
            self.assertEqual(build_result.slide_build_results[0].assets_used[0].resolved_path, str(source_asset))
            self.assertEqual(build_result.slide_build_results[0].warnings, [])

    def test_renderer_materializes_conceptual_visual_without_source_asset(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PPTXBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "deck.pptx"
            with patch("app.renderers.pptx_renderer.importlib.import_module", return_value=_FakePptxModule()):
                build_result = agent.build(
                    presentation_plan=_build_minimal_plan(),
                    speaker_notes=_build_minimal_notes(),
                    generated_visuals=_build_conceptual_visuals(),
                    output_path=output_path,
                    asset_map={},
                )

            self.assertTrue(output_path.is_file())
            self.assertEqual(build_result.build_status, "success")
            self.assertEqual(
                build_result.slide_build_results[0].assets_used[0].resolved_path,
                "generated:inline_conceptual_card",
            )
            self.assertEqual(build_result.slide_build_results[0].warnings, [])

    def test_renderer_uses_planned_source_visual_when_generated_visuals_empty(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = PPTXBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDAT"
            b"\x08\x99c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00"
            b"\x00\x00\x00IEND\xaeB`\x82"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            output_path = temp_dir / "deck.pptx"
            source_asset = temp_dir / "planned-source.png"
            source_asset.write_bytes(png_bytes)

            with patch("app.renderers.pptx_renderer.importlib.import_module", return_value=_FakePptxModule()):
                build_result = agent.build(
                    presentation_plan=_build_plan_with_source_visual("A_FIG_01"),
                    speaker_notes=_build_minimal_notes(),
                    generated_visuals=_build_minimal_visuals(),
                    output_path=output_path,
                    asset_map={"A_FIG_01": str(source_asset)},
                )

            self.assertTrue(output_path.is_file())
            self.assertEqual(build_result.build_status, "success")
            self.assertEqual(build_result.slide_build_results[0].assets_used[0].resolved_path, str(source_asset))
            self.assertEqual(build_result.slide_build_results[0].warnings, [])

    def test_resolve_template_path_prefers_repo_canonical_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "repo-default.pptx"
            with zipfile.ZipFile(template_path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types></Types>")

            with patch.object(PPTXRenderer, "_repo_template_candidates", return_value=[template_path]), patch.object(
                PPTXRenderer,
                "_find_fallback_template",
                return_value=None,
            ):
                resolved_path, template_used, warnings = PPTXRenderer._resolve_template_path(_FakePptxModuleWithFile())

        self.assertEqual(resolved_path, template_path.resolve())
        self.assertEqual(template_used, str(template_path.resolve()))
        self.assertTrue(any("repository canonical template" in warning for warning in warnings))

    def test_resolve_template_path_raises_with_repo_path_hint_when_no_template_available(self) -> None:
        with patch.object(PPTXRenderer, "_repo_template_candidates", return_value=[]), patch.object(
            PPTXRenderer,
            "_find_fallback_template",
            return_value=None,
        ):
            with self.assertRaises(RuntimeError) as context:
                PPTXRenderer._resolve_template_path(_FakePptxModuleWithFile())

        self.assertIn("backend/templates/pptx/default.pptx", str(context.exception))


if __name__ == "__main__":
    unittest.main()
