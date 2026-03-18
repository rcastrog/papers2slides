"""Tests for deterministic external-reference citation audit guard."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.audit_report import AuditReport
from app.models.reference_index import ReferenceIndex
from app.models.presentation_plan import PresentationPlan
from app.orchestrator.workflow import (
    _apply_citation_repairs,
    _enforce_external_reference_citation_audit_guard,
    _enforce_retrieved_reference_citation_policy,
)


def _build_plan(*, include_reference_citation: bool) -> PresentationPlan:
    citations = [{"short_citation": "Massenkoff & McCrory, 2026", "source_kind": "source_paper"}]
    if include_reference_citation:
        citations.append({"short_citation": "Eloundou et al., 2023", "source_kind": "reference_paper"})

    return PresentationPlan.model_validate(
        {
            "deck_metadata": {
                "title": "Deck",
                "subtitle": "Sub",
                "language": "en",
                "presentation_style": "journal_club",
                "target_audience": "technical_adjacent",
                "target_duration_minutes": 20,
                "target_slide_count": 2,
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
                    "key_points": ["Tasks scored using Eloundou et al. (2023)."],
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
                    "citations": citations,
                    "speaker_note_hooks": [],
                    "confidence_notes": [],
                    "layout_hint": "default",
                }
            ],
            "global_warnings": [],
            "plan_confidence": "medium",
        }
    )


def _build_clean_audit() -> AuditReport:
    return AuditReport.model_validate(
        {
            "audit_status": "completed",
            "deck_risk_level": "low",
            "slide_audits": [
                {
                    "slide_number": 1,
                    "slide_title": "Method",
                    "overall_support": "supported",
                    "findings": [],
                    "required_action": "none",
                }
            ],
            "deck_level_findings": [],
            "repair_priority": [],
            "global_warnings": [],
        }
    )


class WorkflowAuditGuardTests(unittest.TestCase):
    def test_fails_audit_when_external_reference_has_no_reference_citation(self) -> None:
        plan = _build_plan(include_reference_citation=False)
        guarded = _enforce_external_reference_citation_audit_guard(
            audit_report=_build_clean_audit(),
            presentation_plan=plan,
        )

        self.assertEqual(guarded.audit_status, "failed")
        self.assertEqual(guarded.deck_risk_level, "high")
        self.assertEqual(guarded.slide_audits[0].required_action, "add_citation")
        self.assertTrue(any(item.category == "citation_issue" for item in guarded.slide_audits[0].findings))

    def test_keeps_audit_when_reference_citation_exists(self) -> None:
        plan = _build_plan(include_reference_citation=True)
        guarded = _enforce_external_reference_citation_audit_guard(
            audit_report=_build_clean_audit(),
            presentation_plan=plan,
        )

        self.assertEqual(guarded.audit_status, "completed")
        self.assertEqual(guarded.deck_risk_level, "low")
        self.assertFalse(guarded.global_warnings)

    def test_drops_non_retrieved_reference_citations_before_render(self) -> None:
        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "technical_adjacent",
                    "target_duration_minutes": 20,
                    "target_slide_count": 2,
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
                        "key_points": ["Point"],
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
                        "source_support": [
                            {"support_type": "reference_summary", "support_id": "R001", "support_note": "ok"},
                            {"support_type": "reference_summary", "support_id": "R002", "support_note": "not found"},
                        ],
                        "citations": [
                            {"short_citation": "Reference R001 unresolved", "source_kind": "reference_paper"},
                            {"short_citation": "Reference R002 unresolved", "source_kind": "reference_paper"},
                            {"short_citation": "Unknown et al., 2010", "source_kind": "reference_paper"},
                            {"short_citation": "Vaswani et al., 2017", "source_kind": "source_paper"},
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

        reference_index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "One",
                        "parsed_reference": {
                            "title": "One",
                            "authors": ["A. Author"],
                            "venue_or_source": "",
                            "year": "2020",
                            "arxiv_id": "",
                            "doi": "",
                        },
                        "parsing_confidence": "high",
                        "retrieval_status": "retrieved",
                        "matched_record": {
                            "title": "One",
                            "authors": ["A. Author"],
                            "year": "2020",
                            "source": "doi",
                            "url": "https://doi.org/10.1000/test",
                            "pdf_path": "x.pdf",
                            "reference_folder_path": "x",
                        },
                        "match_confidence": "high",
                        "alternative_candidates": [],
                        "failure_reason": "",
                        "notes": [],
                    },
                    {
                        "reference_id": "R002",
                        "original_reference_text": "Two",
                        "parsed_reference": {
                            "title": "Two",
                            "authors": ["B. Author"],
                            "venue_or_source": "",
                            "year": "2021",
                            "arxiv_id": "",
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
                    },
                ],
                "retrieval_summary": {
                    "total_references": 2,
                    "retrieved_count": 1,
                    "ambiguous_count": 0,
                    "not_found_count": 1,
                    "warnings": [],
                },
            }
        )

        filtered = _enforce_retrieved_reference_citation_policy(
            plan=plan,
            reference_index=reference_index,
        )

        citations = filtered.slides[0].citations
        ref_citations = [item for item in citations if item.source_kind == "reference_paper"]
        self.assertEqual(len(ref_citations), 1)
        self.assertEqual(ref_citations[0].short_citation, "Author et al., 2020")
        support_ids = [item.support_id for item in filtered.slides[0].source_support if item.support_type == "reference_summary"]
        self.assertEqual(support_ids, ["R001"])

    def test_citation_repair_adds_reference_citation_for_flagged_slide(self) -> None:
        plan = _build_plan(include_reference_citation=False)
        audit = AuditReport.model_validate(
            {
                "audit_status": "failed",
                "deck_risk_level": "high",
                "slide_audits": [
                    {
                        "slide_number": 1,
                        "slide_title": "Method",
                        "overall_support": "unsupported",
                        "findings": [
                            {
                                "severity": "high",
                                "category": "citation_issue",
                                "description": "Missing reference citation",
                                "evidence_basis": [
                                    {
                                        "source_type": "presentation_plan",
                                        "source_id": "slide_1",
                                        "note": "External-work mention detected.",
                                    }
                                ],
                                "recommended_fix": "Add reference citation",
                            }
                        ],
                        "required_action": "add_citation",
                    }
                ],
                "deck_level_findings": [],
                "repair_priority": [],
                "global_warnings": [],
            }
        )

        repaired = _apply_citation_repairs(plan, audit)

        reference_citations = [
            citation
            for citation in repaired.slides[0].citations
            if citation.source_kind == "reference_paper"
        ]

        self.assertTrue(reference_citations)
        self.assertTrue(any("Citation coverage tightened in repair cycle." in warning for warning in repaired.global_warnings))

    def test_keeps_variant_reference_label_when_it_maps_to_retrieved_entry(self) -> None:
        plan = PresentationPlan.model_validate(
            {
                "deck_metadata": {
                    "title": "Deck",
                    "subtitle": "Sub",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "technical_adjacent",
                    "target_duration_minutes": 20,
                    "target_slide_count": 2,
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
                        "key_points": ["Uses prior work."],
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
                        "citations": [
                            {"short_citation": "Eloundou et al. (2023)", "source_kind": "reference_paper"},
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

        reference_index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "Eloundou et al. 2023",
                        "parsed_reference": {
                            "title": "Large Language Models and Labor",
                            "authors": ["Tyna Eloundou"],
                            "venue_or_source": "arXiv",
                            "year": "2023",
                            "arxiv_id": "2303.10130",
                            "doi": "",
                        },
                        "parsing_confidence": "high",
                        "retrieval_status": "retrieved",
                        "matched_record": {
                            "title": "Large Language Models and Labor",
                            "authors": ["Tyna Eloundou"],
                            "year": "2023",
                            "source": "arxiv",
                            "url": "https://arxiv.org/abs/2303.10130",
                            "pdf_path": "C:/tmp/r001.pdf",
                            "reference_folder_path": "C:/tmp/R001",
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

        filtered = _enforce_retrieved_reference_citation_policy(
            plan=plan,
            reference_index=reference_index,
        )

        ref_citations = [item for item in filtered.slides[0].citations if item.source_kind == "reference_paper"]
        self.assertEqual(len(ref_citations), 1)
        self.assertEqual(ref_citations[0].short_citation, "Eloundou et al., 2023")


if __name__ == "__main__":
    unittest.main()
