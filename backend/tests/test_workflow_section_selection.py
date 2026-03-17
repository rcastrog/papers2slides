"""Regression tests for workflow section selection helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.artifact_manifest import ArtifactManifest
from app.models.generated_visuals import GeneratedVisuals
from app.models.reference_index import ReferenceIndex
from app.models.reference_summary import ReferenceSummary
from app.models.presentation_plan import PresentationPlan
from app.orchestrator.workflow import (
    _apply_citation_purpose_policy,
    _apply_generated_visual_last_resort_policy,
    _apply_reference_citation_policy,
    _enforce_slide_density_and_target_count,
    _ensure_reference_index_coverage,
    _normalize_reference_citation_labels,
    _apply_source_only_visual_policy,
    _apply_source_first_visual_policy,
    _normalize_workflow_options,
    _resolve_effective_llm_settings,
    _select_sections_for_analysis,
)
from app.config import LLMSettings
from app.utils.section_splitter import SectionCandidate


class WorkflowSectionSelectionTests(unittest.TestCase):
    def test_selects_sections_from_parsed_titles_and_ignores_references(self) -> None:
        full_text = """
Key findings
Figure and claim summary.

Introduction
Background and motivation.

Measuring exposure
Method details.

How exposure tracks with projected job growth and worker characteristics
Result details.

Prioritizing outcomes
More results.

Discussion
Interpretation.

References
[1] ...
""".strip()

        parsed_titles = [
            "Key findings",
            "Introduction",
            "Measuring exposure",
            "How exposure tracks with projected job growth and worker characteristics",
            "Prioritizing outcomes",
            "Discussion",
            "References",
        ]

        fallback = [
            SectionCandidate(
                section_title="Discussion",
                start_index=0,
                end_index=len(full_text),
                text=full_text,
                confidence=0.9,
                inferred=False,
            )
        ]

        selected = _select_sections_for_analysis(
            full_text=full_text,
            parsed_section_titles=parsed_titles,
            fallback_candidates=fallback,
        )

        self.assertEqual([item.section_title for item in selected], [
            "Key findings",
            "Introduction",
            "Measuring exposure",
            "How exposure tracks with projected job growth and worker characteristics",
            "Prioritizing outcomes",
        ])

    def test_falls_back_when_parsed_titles_are_not_found(self) -> None:
        full_text = "Discussion\nOnly one section body."
        fallback = [
            SectionCandidate(
                section_title="Discussion",
                start_index=0,
                end_index=len(full_text),
                text=full_text,
                confidence=0.9,
                inferred=False,
            )
        ]

        selected = _select_sections_for_analysis(
            full_text=full_text,
            parsed_section_titles=["Missing Section"],
            fallback_candidates=fallback,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].section_title, "Discussion")


class WorkflowVisualPolicyTests(unittest.TestCase):
    def test_injects_source_visual_when_support_artifact_exists(self) -> None:
        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": 10,
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
                        "objective": "Show result",
                        "key_points": ["KP"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "generated_conceptual",
                                "asset_id": "GV01",
                                "source_origin": "generated",
                                "usage_mode": "conceptual",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Explain mechanism",
                            }
                        ],
                        "source_support": [
                            {
                                "support_type": "source_artifact",
                                "support_id": "A_FIG_01",
                                "support_note": "Result figure",
                            }
                        ],
                        "citations": [{"short_citation": "Source", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    }
                ],
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

        manifest = ArtifactManifest.model_validate(
            {
                "artifacts": [
                    {
                        "artifact_id": "A_FIG_01",
                        "artifact_label": "Figure 1",
                        "artifact_type": "plot",
                        "page_numbers": [6],
                        "section_id": "S3",
                        "caption": "Caption",
                        "nearby_context_summary": "Summary",
                        "file_path": "source/SRC_P06_IMG01.jpg",
                        "extraction_quality": "high",
                        "readability_for_presentation": "high",
                        "core_message": "Message",
                        "presentation_value": "high",
                        "recommended_action": "reuse_directly",
                        "recommendation_rationale": "Good",
                        "must_preserve_if_adapted": [],
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
        )

        updated = _apply_source_first_visual_policy(
            plan=plan,
            artifact_manifest=manifest,
            asset_map={"A_FIG_01": "C:/tmp/src.png"},
        )

        first_visual = updated.slides[0].visuals[0]
        self.assertEqual(first_visual.asset_id, "A_FIG_01")
        self.assertEqual(first_visual.source_origin, "source_paper")
        self.assertIn("Source-first visual policy", updated.global_warnings[0])

    def test_adds_must_avoid_on_evidence_slide_with_conceptual(self) -> None:
        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": 10,
                },
                "narrative_arc": {
                    "overall_story": "Story",
                    "audience_adaptation_notes": [],
                    "language_adaptation_notes": [],
                },
                "slides": [
                    {
                        "slide_number": 2,
                        "slide_role": "discussion",
                        "title": "Discussion",
                        "objective": "Discuss",
                        "key_points": ["KP"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "generated_conceptual",
                                "asset_id": "GV02",
                                "source_origin": "generated",
                                "usage_mode": "conceptual",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Explain implication",
                            }
                        ],
                        "source_support": [
                            {
                                "support_type": "source_artifact",
                                "support_id": "A_FIG_03",
                                "support_note": "Discussion figure",
                            }
                        ],
                        "citations": [{"short_citation": "Source", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    }
                ],
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

        manifest = ArtifactManifest.model_validate(
            {
                "artifacts": [
                    {
                        "artifact_id": "A_FIG_03",
                        "artifact_label": "Figure 3",
                        "artifact_type": "figure",
                        "page_numbers": [8],
                        "section_id": "S4",
                        "caption": "Caption",
                        "nearby_context_summary": "Summary",
                        "file_path": "source/SRC_P08_IMG01.jpg",
                        "extraction_quality": "high",
                        "readability_for_presentation": "high",
                        "core_message": "Message",
                        "presentation_value": "high",
                        "recommended_action": "reuse_directly",
                        "recommendation_rationale": "Good",
                        "must_preserve_if_adapted": [],
                        "distortion_risk": "low",
                        "ambiguities": [],
                        "notes": [],
                    }
                ],
                "summary": {
                    "artifact_count": 1,
                    "high_value_artifact_ids": ["A_FIG_03"],
                    "high_risk_artifact_ids": [],
                    "equation_artifact_ids": [],
                    "warnings": [],
                },
            }
        )

        updated = _apply_source_first_visual_policy(
            plan=plan,
            artifact_manifest=manifest,
            asset_map={"A_FIG_03": "C:/tmp/src3.png"},
        )

        self.assertIn("Do not use conceptual visuals as evidence", updated.slides[0].must_avoid)


class WorkflowReferenceCitationPolicyTests(unittest.TestCase):
    def _build_minimal_plan(self, key_points: list[str]) -> PresentationPlan:
        return PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "technical_adjacent",
                    "target_duration_minutes": 20,
                    "target_slide_count": 5,
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
                        "title": "Method",
                        "objective": "Explain method",
                        "key_points": key_points,
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "text_only",
                                "asset_id": "none",
                                "source_origin": "none",
                                "usage_mode": "none",
                                "placement_hint": "center_focus",
                                "why_this_visual": "text",
                            }
                        ],
                        "source_support": [],
                        "citations": [{"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    },
                    {
                        "slide_number": 2,
                        "slide_role": "discussion",
                        "title": "Discussion",
                        "objective": "Discuss implications",
                        "key_points": ["Implications"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "text_only",
                                "asset_id": "none",
                                "source_origin": "none",
                                "usage_mode": "none",
                                "placement_hint": "center_focus",
                                "why_this_visual": "text",
                            }
                        ],
                        "source_support": [],
                        "citations": [{"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    },
                ],
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

    def _build_reference_index(self) -> ReferenceIndex:
        return ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "Eloundou et al. 2023",
                        "parsed_reference": {
                            "title": "Gpts are gpts",
                            "authors": ["Tyna Eloundou", "Sam Manning"],
                            "venue_or_source": "arXiv",
                            "year": "2023",
                            "arxiv_id": "2303.10130",
                            "doi": "",
                        },
                        "parsing_confidence": "high",
                        "retrieval_status": "retrieved",
                        "matched_record": {
                            "title": "Gpts are gpts",
                            "authors": ["Tyna Eloundou", "Sam Manning"],
                            "year": "2023",
                            "source": "arxiv",
                            "url": "https://arxiv.org/abs/2303.10130",
                            "pdf_path": "references/R001/2303.10130.pdf",
                            "reference_folder_path": "references/R001",
                        },
                        "match_confidence": "high",
                        "alternative_candidates": [],
                        "failure_reason": "",
                        "notes": [],
                    }
                ],
                "retrieval_summary": {
                    "total_references": 1,
                    "retrieved_count": 1,
                    "ambiguous_count": 0,
                    "not_found_count": 0,
                    "warnings": [],
                },
            }
        )

    def _build_reference_summaries(self) -> list[ReferenceSummary]:
        return [
            ReferenceSummary.model_validate(
                {
                    "reference_id": "R001",
                    "reference_title": "Gpts are gpts",
                    "summary": {
                        "main_topic": "LLM labor effects",
                        "main_contribution": "Early labor market impact analysis",
                        "brief_summary": "Contextual benchmark",
                    },
                    "relation_to_source_paper": {
                        "relation_type": ["background_context"],
                        "description": "Relevant background",
                        "importance_for_source_presentation": "high",
                    },
                    "useful_points_for_main_presentation": [],
                    "possible_useful_artifacts": [],
                    "mention_recommendation": {
                        "should_mention_in_final_deck": True,
                        "recommended_scope": "one_bullet_context",
                        "rationale": "Useful context",
                    },
                    "warnings": [],
                    "confidence": "high",
                }
            )
        ]


class WorkflowRuntimeOptionTests(WorkflowReferenceCitationPolicyTests):
    def test_deterministic_mode_forces_temperature_zero(self) -> None:
        base = LLMSettings(llm_provider="openai", openai_api_key="k", llm_temperature=0.7)
        options = _normalize_workflow_options(
            {
                "advanced_options": {
                    "deterministic_mode": True,
                    "llm_temperature": 0.8,
                }
            }
        )

        effective = _resolve_effective_llm_settings(base, options)
        self.assertEqual(effective.llm_temperature, 0.0)

    def test_last_resort_generated_visual_policy_drops_source_backed_slides(self) -> None:
        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": 10,
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
                        "objective": "Show result",
                        "key_points": ["KP"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "source_chart",
                                "asset_id": "A_FIG_01",
                                "source_origin": "source_paper",
                                "usage_mode": "reuse",
                                "placement_hint": "left_visual_right_text",
                                "why_this_visual": "Source evidence",
                            }
                        ],
                        "source_support": [],
                        "citations": [{"short_citation": "Source", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    },
                    {
                        "slide_number": 2,
                        "slide_role": "method",
                        "title": "Method",
                        "objective": "Explain method",
                        "key_points": ["KP"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "text_only",
                                "asset_id": "none",
                                "source_origin": "none",
                                "usage_mode": "none",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Text",
                            }
                        ],
                        "source_support": [],
                        "citations": [{"short_citation": "Source", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    },
                ],
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

        generated = GeneratedVisuals.model_validate(
            {
                "generated_visuals": [
                    {
                        "visual_id": "GV01",
                        "slide_number": 1,
                        "slide_title": "Results",
                        "visual_purpose": "Conceptual explanation",
                        "visual_kind": "concept_map",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s1"],
                            "grounded_in_source_artifacts": ["A_FIG_01"],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Simple",
                            "main_elements": ["Node"],
                            "labels_or_text": ["Label"],
                            "style_notes": ["Clean"],
                            "language": "en",
                        },
                        "safety_notes": [],
                        "image_generation_prompt": "Prompt",
                    },
                    {
                        "visual_id": "GV02",
                        "slide_number": 2,
                        "slide_title": "Method",
                        "visual_purpose": "Conceptual method overview",
                        "visual_kind": "workflow",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s2"],
                            "grounded_in_source_artifacts": [],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Simple",
                            "main_elements": ["Node"],
                            "labels_or_text": ["Label"],
                            "style_notes": ["Clean"],
                            "language": "en",
                        },
                        "safety_notes": [],
                        "image_generation_prompt": "Prompt",
                    },
                ],
                "global_visual_warnings": [],
            }
        )

        updated = _apply_generated_visual_last_resort_policy(
            generated_visuals=generated,
            presentation_plan=plan,
            asset_map={"A_FIG_01": "C:/tmp/source.png"},
        )

        kept_ids = [item.visual_id for item in updated.generated_visuals]
        self.assertEqual(kept_ids, ["GV02"])
        self.assertTrue(any("Last-resort policy" in item for item in updated.global_visual_warnings))

    def test_source_only_policy_removes_generated_visuals_from_plan(self) -> None:
        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": 10,
                },
                "narrative_arc": {
                    "overall_story": "Story",
                    "audience_adaptation_notes": [],
                    "language_adaptation_notes": [],
                },
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_role": "motivation",
                        "title": "Motivation",
                        "objective": "Explain",
                        "key_points": ["KP"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "generated_conceptual",
                                "asset_id": "none",
                                "source_origin": "generated",
                                "usage_mode": "conceptual",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Concept visual",
                            }
                        ],
                        "source_support": [],
                        "citations": [{"short_citation": "Source", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    },
                    {
                        "slide_number": 2,
                        "slide_role": "result",
                        "title": "Result",
                        "objective": "Show",
                        "key_points": ["KP"],
                        "must_avoid": [],
                        "visuals": [
                            {
                                "visual_type": "source_figure",
                                "asset_id": "A_FIG_01",
                                "source_origin": "source_paper",
                                "usage_mode": "reuse",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Source",
                            }
                        ],
                        "source_support": [],
                        "citations": [{"short_citation": "Source", "source_kind": "source_paper"}],
                        "speaker_note_hooks": [],
                        "confidence_notes": [],
                        "layout_hint": "default",
                    },
                ],
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

        updated = _apply_source_only_visual_policy(plan=plan)

        self.assertEqual(len(updated.slides[0].visuals), 0)
        self.assertEqual(len(updated.slides[1].visuals), 1)
        self.assertTrue(any("source-only visual policy" in item.lower() for item in updated.global_warnings))

    def test_reference_policy_removes_reference_citations_from_title_slide(self) -> None:
        plan = self._build_minimal_plan(["Method details without named references."])
        payload = plan.model_dump()
        payload["slides"][0]["slide_role"] = "title"
        payload["slides"][0]["citations"] = [
            {"short_citation": "Eloundou et al., 2023", "source_kind": "reference_paper"}
        ]
        title_plan = PresentationPlan.model_validate(payload)

        updated = _apply_reference_citation_policy(
            plan=title_plan,
            reference_index=self._build_reference_index(),
            reference_summaries=self._build_reference_summaries(),
        )

        self.assertFalse(any(item.source_kind == "reference_paper" for item in updated.slides[0].citations))

    def test_reference_label_normalization_replaces_malformed_title_text(self) -> None:
        plan = self._build_minimal_plan(["Method details without named references."])
        payload = plan.model_dump()
        payload["slides"][1]["citations"] = [
            {"short_citation": "Quasi-experimental shift-share research designs", "source_kind": "reference_paper"},
            {"short_citation": "Massenkoff & McCrory, 2026 | Quasi-experimental shift-share research designs", "source_kind": "reference_paper"},
            {"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"},
        ]
        plan_with_noise = PresentationPlan.model_validate(payload)

        normalized = _normalize_reference_citation_labels(
            plan=plan_with_noise,
            reference_index=self._build_reference_index(),
        )

        slide_citations = normalized.slides[1].citations
        ref_citations = [item.short_citation for item in slide_citations if item.source_kind == "reference_paper"]
        self.assertIn("Eloundou & Manning, 2023", ref_citations)
        self.assertNotIn("Quasi-experimental shift-share research designs", ref_citations)
        self.assertEqual(len(ref_citations), len(set(ref_citations)))

    def test_reference_label_normalization_marks_unresolved_reference_ids(self) -> None:
        plan = self._build_minimal_plan(["Method details without named references."])
        payload = plan.model_dump()
        payload["slides"][1]["citations"] = [
            {"short_citation": "Reference R018", "source_kind": "reference_paper"},
            {"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"},
        ]

        normalized = _normalize_reference_citation_labels(
            plan=PresentationPlan.model_validate(payload),
            reference_index=self._build_reference_index(),
        )

        ref_citations = [item.short_citation for item in normalized.slides[1].citations if item.source_kind == "reference_paper"]
        self.assertIn("Reference R018 unresolved", ref_citations)

    def test_citation_purpose_policy_infers_expected_purposes(self) -> None:
        plan = self._build_minimal_plan(["Method details without named references."])
        payload = plan.model_dump()
        payload["slides"][0]["slide_role"] = "title"
        payload["slides"][0]["citations"] = [
            {"short_citation": "Source paper", "source_kind": "source_paper"}
        ]
        payload["slides"][1]["slide_role"] = "method"
        payload["slides"][1]["citations"] = [
            {"short_citation": "Eloundou & Manning, 2023", "source_kind": "reference_paper"},
            {"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"},
        ]

        updated = _apply_citation_purpose_policy(plan=PresentationPlan.model_validate(payload))

        self.assertEqual(updated.slides[0].citations[0].citation_purpose, "attribution")
        self.assertEqual(updated.slides[1].citations[0].citation_purpose, "method_background")
        self.assertEqual(updated.slides[1].citations[1].citation_purpose, "source_of_claim")

    def test_injects_reference_citation_for_matching_slide_text(self) -> None:
        plan = self._build_minimal_plan(["Tasks are scored using Eloundou et al. (2023)."])
        updated = _apply_reference_citation_policy(
            plan=plan,
            reference_index=self._build_reference_index(),
            reference_summaries=self._build_reference_summaries(),
        )

        citations = updated.slides[0].citations
        self.assertTrue(any(item.source_kind == "reference_paper" for item in citations))
        self.assertIn("Auto-policy: injected", updated.global_warnings[-1])
        self.assertIn("max_per_slide=4", updated.global_warnings[-1])

    def test_does_not_inject_reference_citation_without_text_evidence(self) -> None:
        plan = self._build_minimal_plan(["Method details without named references."])
        updated = _apply_reference_citation_policy(
            plan=plan,
            reference_index=self._build_reference_index(),
            reference_summaries=self._build_reference_summaries(),
        )

        discussion_citations = [item for item in updated.slides[1].citations if item.source_kind == "reference_paper"]
        self.assertEqual(len(discussion_citations), 0)

    def test_reference_policy_respects_max_citations_per_slide(self) -> None:
        plan = self._build_minimal_plan(["Method details discuss artificial intelligence jobs evidence."])
        reference_index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "Eloundou et al. 2023",
                        "parsed_reference": {
                            "title": "Gpts are gpts",
                            "authors": ["Tyna Eloundou", "Sam Manning"],
                            "venue_or_source": "arXiv",
                            "year": "2023",
                            "arxiv_id": "2303.10130",
                            "doi": "",
                        },
                        "parsing_confidence": "high",
                        "retrieval_status": "retrieved",
                        "matched_record": {
                            "title": "Gpts are gpts",
                            "authors": ["Tyna Eloundou", "Sam Manning"],
                            "year": "2023",
                            "source": "arxiv",
                            "url": "https://arxiv.org/abs/2303.10130",
                            "pdf_path": "references/R001/2303.10130.pdf",
                            "reference_folder_path": "references/R001",
                        },
                        "match_confidence": "high",
                        "alternative_candidates": [],
                        "failure_reason": "",
                        "notes": [],
                    },
                    {
                        "reference_id": "R002",
                        "original_reference_text": "Acemoglu et al. 2022",
                        "parsed_reference": {
                            "title": "Artificial intelligence and jobs",
                            "authors": ["Daron Acemoglu", "David Autor"],
                            "venue_or_source": "JLE",
                            "year": "2022",
                            "arxiv_id": "",
                            "doi": "10.1086/718327",
                        },
                        "parsing_confidence": "high",
                        "retrieval_status": "retrieved",
                        "matched_record": {
                            "title": "Artificial intelligence and jobs",
                            "authors": ["Daron Acemoglu", "David Autor"],
                            "year": "2022",
                            "source": "doi",
                            "url": "https://doi.org/10.1086/718327",
                            "pdf_path": "references/R002/10.1086_718327.pdf",
                            "reference_folder_path": "references/R002",
                        },
                        "match_confidence": "high",
                        "alternative_candidates": [],
                        "failure_reason": "",
                        "notes": [],
                    },
                ],
                "retrieval_summary": {
                    "total_references": 2,
                    "retrieved_count": 2,
                    "ambiguous_count": 0,
                    "not_found_count": 0,
                    "warnings": [],
                },
            }
        )
        summaries = [
            ReferenceSummary.model_validate(
                {
                    "reference_id": "R001",
                    "reference_title": "Gpts are gpts",
                    "summary": {
                        "main_topic": "LLM labor effects",
                        "main_contribution": "Early labor market impact analysis",
                        "brief_summary": "Contextual benchmark",
                    },
                    "relation_to_source_paper": {
                        "relation_type": ["method_ancestry"],
                        "description": "Method context",
                        "importance_for_source_presentation": "high",
                    },
                    "useful_points_for_main_presentation": [
                        {
                            "point": "Useful for method setup",
                            "usage_type": "method_context",
                            "support_strength": "strong",
                        }
                    ],
                    "possible_useful_artifacts": [],
                    "mention_recommendation": {
                        "should_mention_in_final_deck": True,
                        "recommended_scope": "one_bullet_context",
                        "rationale": "Method baseline",
                    },
                    "warnings": [],
                    "confidence": "high",
                }
            ),
            ReferenceSummary.model_validate(
                {
                    "reference_id": "R002",
                    "reference_title": "Artificial intelligence and jobs",
                    "summary": {
                        "main_topic": "Labor market vacancies",
                        "main_contribution": "Evidence on jobs",
                        "brief_summary": "Supports empirical interpretation",
                    },
                    "relation_to_source_paper": {
                        "relation_type": ["supporting_evidence"],
                        "description": "Empirical context",
                        "importance_for_source_presentation": "high",
                    },
                    "useful_points_for_main_presentation": [
                        {
                            "point": "Useful for discussion of evidence",
                            "usage_type": "result_context",
                            "support_strength": "strong",
                        }
                    ],
                    "possible_useful_artifacts": [],
                    "mention_recommendation": {
                        "should_mention_in_final_deck": True,
                        "recommended_scope": "one_supporting_slide_note",
                        "rationale": "Strong supporting context",
                    },
                    "warnings": [],
                    "confidence": "high",
                }
            ),
        ]

        updated = _apply_reference_citation_policy(
            plan=plan,
            reference_index=reference_index,
            reference_summaries=summaries,
            max_reference_citations_per_slide=2,
        )

        total_ref_citations = sum(
            1
            for slide in updated.slides
            for item in slide.citations
            if item.source_kind == "reference_paper"
        )
        self.assertLessEqual(total_ref_citations, 2)
        self.assertGreaterEqual(total_ref_citations, 1)

    def test_reference_policy_does_not_inject_non_retrieved_reference(self) -> None:
        plan = self._build_minimal_plan(["Method details without named references."])
        reference_index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "Eloundou et al. 2023",
                        "parsed_reference": {
                            "title": "Gpts are gpts",
                            "authors": ["Tyna Eloundou", "Sam Manning"],
                            "venue_or_source": "arXiv",
                            "year": "2023",
                            "arxiv_id": "2303.10130",
                            "doi": "",
                        },
                        "parsing_confidence": "high",
                        "retrieval_status": "not_found",
                        "matched_record": {
                            "title": "",
                            "authors": [],
                            "year": "",
                            "source": "other",
                            "url": "",
                            "pdf_path": "",
                            "reference_folder_path": "",
                        },
                        "match_confidence": "low",
                        "alternative_candidates": [],
                        "failure_reason": "not found",
                        "notes": [],
                    }
                ],
                "retrieval_summary": {
                    "total_references": 1,
                    "retrieved_count": 0,
                    "ambiguous_count": 0,
                    "not_found_count": 1,
                    "warnings": [],
                },
            }
        )

        updated = _apply_reference_citation_policy(
            plan=plan,
            reference_index=reference_index,
            reference_summaries=self._build_reference_summaries(),
        )

        discussion_citations = [item for item in updated.slides[1].citations if item.source_kind == "reference_paper"]
        self.assertEqual(len(discussion_citations), 0)

    def test_reference_policy_limits_reuse_across_deck(self) -> None:
        plan = self._build_minimal_plan(["Tasks are scored using Eloundou et al. (2023)."])
        payload = plan.model_dump()
        payload["slides"].append(
            {
                "slide_number": 3,
                "slide_role": "result",
                "title": "Result",
                "objective": "Show evidence",
                "key_points": ["Eloundou 2023 evidence"],
                "must_avoid": [],
                "visuals": [
                    {
                        "visual_type": "text_only",
                        "asset_id": "none",
                        "source_origin": "none",
                        "usage_mode": "none",
                        "placement_hint": "center_focus",
                        "why_this_visual": "text",
                    }
                ],
                "source_support": [],
                "citations": [{"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"}],
                "speaker_note_hooks": [],
                "confidence_notes": [],
                "layout_hint": "default",
            }
        )
        payload["slides"].append(
            {
                "slide_number": 4,
                "slide_role": "result",
                "title": "Result 2",
                "objective": "Show additional evidence",
                "key_points": ["Eloundou 2023 benchmark"],
                "must_avoid": [],
                "visuals": [
                    {
                        "visual_type": "text_only",
                        "asset_id": "none",
                        "source_origin": "none",
                        "usage_mode": "none",
                        "placement_hint": "center_focus",
                        "why_this_visual": "text",
                    }
                ],
                "source_support": [],
                "citations": [{"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"}],
                "speaker_note_hooks": [],
                "confidence_notes": [],
                "layout_hint": "default",
            }
        )

        updated = _apply_reference_citation_policy(
            plan=PresentationPlan.model_validate(payload),
            reference_index=self._build_reference_index(),
            reference_summaries=self._build_reference_summaries(),
            max_reference_citations_per_slide=2,
            max_slides_per_reference=2,
        )

        appearance_count = 0
        for slide in updated.slides:
            if any(item.source_kind == "reference_paper" for item in slide.citations):
                appearance_count += 1
        self.assertLessEqual(appearance_count, 2)

    def test_reference_index_coverage_backfills_parsed_reference_from_raw_text(self) -> None:
        reference_index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "Acemoglu, Daron and Pascual Restrepo, \"Robots and Jobs: Evidence from US Labor Markets,\" Journal of Political Economy, 2020.",
                        "parsed_reference": {
                            "title": "",
                            "authors": [],
                            "venue_or_source": "",
                            "year": "",
                            "arxiv_id": "",
                            "doi": "",
                        },
                        "parsing_confidence": "low",
                        "retrieval_status": "not_found",
                        "matched_record": {
                            "title": "",
                            "authors": [],
                            "year": "",
                            "source": "other",
                            "url": "",
                            "pdf_path": "",
                            "reference_folder_path": "",
                        },
                        "match_confidence": "low",
                        "alternative_candidates": [],
                        "failure_reason": "",
                        "notes": [],
                    }
                ],
                "retrieval_summary": {
                    "total_references": 1,
                    "retrieved_count": 0,
                    "ambiguous_count": 0,
                    "not_found_count": 1,
                    "warnings": [],
                },
            }
        )

        updated, _warnings = _ensure_reference_index_coverage(
            reference_index=reference_index,
            references_raw=[
                "Acemoglu, Daron and Pascual Restrepo, \"Robots and Jobs: Evidence from US Labor Markets,\" Journal of Political Economy, 2020."
            ],
        )

        entry = updated.reference_index[0]
        self.assertEqual(entry.parsed_reference.title, "Robots and Jobs: Evidence from US Labor Markets")
        self.assertEqual(entry.parsed_reference.year, "2020")
        self.assertGreaterEqual(len(entry.parsed_reference.authors), 2)
        self.assertEqual(entry.parsing_confidence, "medium")

    def test_reference_index_coverage_normalizes_merged_author_candidates(self) -> None:
        reference_index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "Hong, Stuart Ritchie, Tim Belonax, Kevin K. Troy, Dario Amodei, Jared Kaplan, Jack Clark, and Deep Ganguli, \"Which Economic Tasks are Performed with AI?\", 2025.",
                        "parsed_reference": {
                            "title": "",
                            "authors": [],
                            "venue_or_source": "",
                            "year": "",
                            "arxiv_id": "",
                            "doi": "",
                        },
                        "parsing_confidence": "low",
                        "retrieval_status": "not_found",
                        "matched_record": {
                            "title": "",
                            "authors": [],
                            "year": "",
                            "source": "other",
                            "url": "",
                            "pdf_path": "",
                            "reference_folder_path": "",
                        },
                        "match_confidence": "low",
                        "alternative_candidates": [],
                        "failure_reason": "",
                        "notes": [],
                    }
                ],
                "retrieval_summary": {
                    "total_references": 1,
                    "retrieved_count": 0,
                    "ambiguous_count": 0,
                    "not_found_count": 1,
                    "warnings": [],
                },
            }
        )

        updated, _warnings = _ensure_reference_index_coverage(
            reference_index=reference_index,
            references_raw=[
                "Hong, Stuart Ritchie, Tim Belonax, Kevin K. Troy, Dario Amodei, Jared Kaplan, Jack Clark, and Deep Ganguli, \"Which Economic Tasks are Performed with AI?\", 2025."
            ],
        )

        authors = updated.reference_index[0].parsed_reference.authors
        self.assertIn("Stuart Ritchie Hong", authors)
        self.assertIn("Tim Belonax", authors)
        self.assertIn("Kevin K. Troy", authors)
        self.assertIn("Dario Amodei", authors)
        self.assertIn("Jared Kaplan", authors)
        self.assertNotIn("Kevin K. Troy Belonax", authors)
        self.assertNotIn("Jared Kaplan Amodei", authors)


class WorkflowStructuralOrderingTests(unittest.TestCase):
    def _build_plan(self, slides: list[dict[str, object]], target_count: int, language: str = "en") -> PresentationPlan:
        return PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": language,
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": target_count,
                },
                "narrative_arc": {
                    "overall_story": "Story",
                    "audience_adaptation_notes": [],
                    "language_adaptation_notes": [],
                },
                "slides": slides,
                "global_warnings": [],
                "plan_confidence": "medium",
            }
        )

    def test_moves_intro_abstract_context_toward_beginning(self) -> None:
        plan = self._build_plan(
            [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Transformer",
                    "objective": "Open",
                    "key_points": ["Title", "Authors", "Venue"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "title_slide",
                },
                {
                    "slide_number": 2,
                    "slide_role": "method",
                    "title": "Method",
                    "objective": "Explain method",
                    "key_points": ["Method one", "Method two", "Method three", "Method four"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [
                        {"support_type": "source_section", "support_id": "S03", "support_note": "Background"}
                    ],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                },
                {
                    "slide_number": 3,
                    "slide_role": "discussion",
                    "title": "Abstract: Supporting Detail",
                    "objective": "Set context",
                    "key_points": ["Context one", "Context two", "Context three", "Context four"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [
                        {"support_type": "source_section", "support_id": "S01", "support_note": "Abstract"}
                    ],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                },
                {
                    "slide_number": 4,
                    "slide_role": "conclusion",
                    "title": "Conclusion",
                    "objective": "Close",
                    "key_points": ["Close one", "Close two", "Close three", "Close four"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                },
            ],
            target_count=4,
        )

        sections = [
            {"section_id": "S01", "section_title": "Abstract", "section_role": ["framing_background"]},
            {"section_id": "S03", "section_title": "Background", "section_role": ["method_explanation"]},
        ]

        updated = _enforce_slide_density_and_target_count(
            plan=plan,
            section_analyses=sections,
            target_slide_count=4,
        )

        titles = [slide.title for slide in updated.slides]
        self.assertEqual(titles[0], "Transformer")
        self.assertEqual(titles[1], "Abstract: Supporting Detail")
        self.assertEqual(titles[-1], "Conclusion")

    def test_conclusion_is_last_core_slide_appendix_may_follow(self) -> None:
        plan = self._build_plan(
            [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Deck",
                    "objective": "Open",
                    "key_points": ["Title", "Authors", "Venue"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "title_slide",
                },
                {
                    "slide_number": 2,
                    "slide_role": "appendix_like_support",
                    "title": "Appendix A",
                    "objective": "Extra detail",
                    "key_points": ["A", "B", "C", "D"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                },
                {
                    "slide_number": 3,
                    "slide_role": "conclusion",
                    "title": "Conclusion",
                    "objective": "Close",
                    "key_points": ["Close one", "Close two", "Close three", "Close four"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                },
            ],
            target_count=3,
        )

        updated = _enforce_slide_density_and_target_count(
            plan=plan,
            section_analyses=[],
            target_slide_count=3,
        )

        titles = [slide.title for slide in updated.slides]
        self.assertEqual(titles[-2], "Conclusion")
        self.assertEqual(titles[-1], "Appendix A")

    def test_backfill_avoids_duplicate_conclusion_support_title(self) -> None:
        plan = self._build_plan(
            [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Deck",
                    "objective": "Open",
                    "key_points": ["Title", "Authors", "Venue"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "title_slide",
                },
                {
                    "slide_number": 2,
                    "slide_role": "conclusion",
                    "title": "Conclusion",
                    "objective": "Close",
                    "key_points": ["Close one", "Close two", "Close three", "Close four"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                },
            ],
            target_count=4,
        )

        sections = [
            {
                "section_id": "S11",
                "section_title": "Conclusion",
                "section_role": ["conclusion_takeaways"],
                "key_claims": [{"claim": "Main takeaway", "notes": ""}],
                "important_details": ["Detail"],
            },
            {
                "section_id": "S12",
                "section_title": "Results",
                "section_role": ["experiment_result_interpretation"],
                "key_claims": [{"claim": "Result improves baseline by 10%", "notes": "validated"}],
                "important_details": ["Confidence interval remains narrow"],
            },
        ]

        updated = _enforce_slide_density_and_target_count(
            plan=plan,
            section_analyses=sections,
            target_slide_count=4,
        )

        titles = [slide.title for slide in updated.slides]
        self.assertEqual(titles.count("Conclusion: Supporting Detail"), 0)

    def test_spanish_backfill_uses_localized_support_text(self) -> None:
        plan = self._build_plan(
            [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Mazo",
                    "objective": "Abrir",
                    "key_points": ["Titulo", "Autores", "Venue"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "title_slide",
                }
            ],
            target_count=2,
            language="es",
        )

        sections = [
            {
                "section_id": "S21",
                "section_title": "Resultados",
                "section_role": ["experiment_result_interpretation"],
                "key_claims": [{"claim": "The method improves throughput", "notes": ""}],
                "important_details": ["Measured over three datasets"],
                "summary": "English fallback summary",
                "why_it_matters": "Explicar hallazgos principales",
            }
        ]

        updated = _enforce_slide_density_and_target_count(
            plan=plan,
            section_analyses=sections,
            target_slide_count=2,
        )

        added_slide = updated.slides[1]
        self.assertIn("Detalle de apoyo", added_slide.title)
        self.assertEqual(added_slide.citations[0].short_citation, "Articulo fuente")
        self.assertTrue(any("evidencia adicional" in point.lower() for point in added_slide.key_points))
        self.assertEqual(len(added_slide.key_points), len(set(added_slide.key_points)))

    def test_spanish_plan_localizes_english_key_points(self) -> None:
        plan = self._build_plan(
            [
                {
                    "slide_number": 1,
                    "slide_role": "result",
                    "title": "Key findings",
                    "objective": "Show impact",
                    "key_points": [
                        "Observed Exposure quantifies the gap between theoretical AI capabilities and actual usage in professional settings.",
                        "A new measure of AI displacement risk.",
                    ],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                }
            ],
            target_count=1,
            language="es",
        )

        updated = _enforce_slide_density_and_target_count(
            plan=plan,
            section_analyses=[],
            target_slide_count=1,
        )

        slide = updated.slides[0]
        self.assertEqual(slide.title, "Resultados clave")
        self.assertTrue(all("Observed Exposure" not in point for point in slide.key_points))
        self.assertTrue(any("exposicion observada" in point.lower() for point in slide.key_points))

    def test_backfill_adds_unique_suffix_when_same_section_repeats(self) -> None:
        plan = self._build_plan(
            [
                {
                    "slide_number": 1,
                    "slide_role": "title",
                    "title": "Deck",
                    "objective": "Open",
                    "key_points": ["Title", "Authors", "Venue"],
                    "must_avoid": [],
                    "visuals": [],
                    "source_support": [],
                    "citations": [],
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "title_slide",
                }
            ],
            target_count=3,
        )

        sections = [
            {
                "section_id": "S31",
                "section_title": "Results",
                "section_role": ["experiment_result_interpretation"],
                "key_claims": [{"claim": "Result improves baseline by 10%", "notes": "validated"}],
                "important_details": ["Confidence interval remains narrow"],
            }
        ]

        updated = _enforce_slide_density_and_target_count(
            plan=plan,
            section_analyses=sections,
            target_slide_count=3,
        )

        titles = [slide.title for slide in updated.slides]
        self.assertIn("Results: Supporting Detail", titles)
        self.assertIn("Results: Supporting Detail (2)", titles)


if __name__ == "__main__":
    unittest.main()
