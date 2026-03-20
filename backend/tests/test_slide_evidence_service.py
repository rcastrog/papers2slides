"""Read-model tests for slide evidence service."""

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

from app.services.slide_evidence_service import SlideEvidenceService


class SlideEvidenceServiceTests(unittest.TestCase):
    def test_build_evidence_maps_claims_citations_and_quality(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir) / "run_20260319"
            self._write_json(
                run_path / "logs" / "run_manifest.json",
                {
                    "run_id": "run_20260319",
                    "status": "completed",
                    "current_stage": "A11",
                },
            )
            self._write_json(
                run_path / "presentation" / "presentation_plan.json",
                {
                    "slides": [
                        {
                            "slide_number": 1,
                            "title": "Results",
                            "key_points": [
                                "Our method improves retrieval precision.",
                                "The improvement is consistent across datasets.",
                            ],
                            "confidence_notes": ["medium confidence"],
                            "citations": [
                                {
                                    "short_citation": "Smith, 2024",
                                    "source_kind": "reference_paper",
                                    "citation_purpose": "source_of_claim",
                                }
                            ],
                            "source_support": [
                                {
                                    "support_type": "source_section",
                                    "support_id": "sec-3",
                                    "support_note": "Section 3 reports precision gains.",
                                }
                            ],
                        }
                    ]
                },
            )
            self._write_json(
                run_path / "references" / "reference_index.json",
                {
                    "reference_index": [
                        {
                            "reference_id": "R001",
                            "original_reference_text": "Smith 2024",
                            "parsed_reference": {
                                "title": "A Retrieval Study",
                                "authors": ["Jane Smith"],
                                "venue_or_source": "arXiv",
                                "year": "2024",
                                "arxiv_id": "",
                                "doi": "",
                            },
                            "parsing_confidence": "high",
                            "retrieval_status": "retrieved",
                            "matched_record": {
                                "title": "A Retrieval Study",
                                "authors": ["Jane Smith"],
                                "year": "2024",
                                "source": "arxiv",
                                "url": "https://arxiv.org/abs/2401.00001",
                                "pdf_path": "references/R001/paper.pdf",
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
                },
            )
            self._write_json(
                run_path / "audit" / "audit_report_initial.json",
                {
                    "audit_status": "completed",
                    "deck_risk_level": "medium",
                    "slide_audits": [
                        {
                            "slide_number": 1,
                            "slide_title": "Results",
                            "overall_support": "weakly_supported",
                            "findings": [
                                {
                                    "severity": "high",
                                    "category": "unsupported_claim",
                                    "description": "One claim is weakly grounded.",
                                    "evidence_basis": [
                                        {
                                            "source_type": "source_section",
                                            "source_id": "sec-3",
                                            "note": "Limited direct evidence.",
                                        }
                                    ],
                                    "recommended_fix": "Add more explicit caveat.",
                                }
                            ],
                            "required_action": "add_caveat",
                        }
                    ],
                    "deck_level_findings": [],
                    "repair_priority": [],
                    "global_warnings": [],
                },
            )

            payload = SlideEvidenceService(run_path).build_evidence()

            self.assertEqual(payload.run_id, "run_20260319")
            self.assertEqual(payload.run_status, "completed")
            self.assertEqual(len(payload.slides), 1)

            slide = payload.slides[0]
            self.assertEqual(slide.slide_id, "slide-1")
            self.assertEqual(slide.claim_count, 2)
            self.assertEqual(slide.no_evidence_claim_count, 0)
            self.assertIn("overall_support:weakly_supported", slide.quality_flags)

            claim = slide.claims[0]
            self.assertFalse(claim.no_evidence)
            self.assertIn("Smith, 2024", claim.citation_labels)
            self.assertIn("https://arxiv.org/abs/2401.00001", claim.citation_links)
            self.assertIn("Section 3 reports precision gains.", claim.source_snippets)

    def test_build_evidence_marks_no_evidence_claims_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir) / "run_20260319_empty"
            self._write_json(
                run_path / "logs" / "run_manifest.json",
                {
                    "run_id": "run_20260319_empty",
                    "status": "completed",
                    "current_stage": "A11",
                },
            )
            self._write_json(
                run_path / "presentation" / "presentation_plan.json",
                {
                    "slides": [
                        {
                            "slide_number": 2,
                            "title": "Discussion",
                            "key_points": ["This claim has no linked source."],
                            "confidence_notes": [],
                            "citations": [],
                            "source_support": [],
                        }
                    ]
                },
            )

            payload = SlideEvidenceService(run_path).build_evidence()

            self.assertEqual(len(payload.slides), 1)
            slide = payload.slides[0]
            self.assertEqual(slide.claim_count, 1)
            self.assertEqual(slide.no_evidence_claim_count, 1)
            self.assertIn("no_evidence", slide.quality_flags)
            self.assertTrue(slide.claims[0].no_evidence)
            self.assertEqual(slide.claims[0].confidence_flag, "low")

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
