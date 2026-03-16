"""E2E regression test: retrieved references must point to existing PDF artifacts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestrator import workflow as workflow_module


class WorkflowE2EReferenceArtifactTests(unittest.TestCase):
    def test_retrieved_reference_entries_always_have_existing_pdf(self) -> None:
        """Run full workflow (mock LLM) and assert retrieval artifact integrity invariant."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            pdf_path = temp_root / "input.pdf"
            self._write_minimal_pdf(pdf_path)

            original_builder = workflow_module._build_fake_responses

            def _patched_fake_responses(*args, **kwargs):
                responses = original_builder(*args, **kwargs)
                for idx, payload in enumerate(responses):
                    if isinstance(payload, dict) and "reference_index" in payload and "retrieval_summary" in payload:
                        entries = payload.get("reference_index", [])
                        injected_entry = False
                        if not entries:
                            entries = [
                                {
                                    "reference_id": "R001",
                                    "original_reference_text": "Synthetic reference",
                                    "parsed_reference": {
                                        "title": "Synthetic Retrieved Ref",
                                        "authors": ["A. Author"],
                                        "venue_or_source": "arXiv",
                                        "year": "2023",
                                        "arxiv_id": "2303.10130",
                                        "doi": "",
                                    },
                                    "parsing_confidence": "medium",
                                    "retrieval_status": "retrieved",
                                    "matched_record": {
                                        "title": "Synthetic Retrieved Ref",
                                        "authors": ["A. Author"],
                                        "year": "2023",
                                        "source": "arxiv",
                                        "url": "https://arxiv.org/abs/2303.10130",
                                        "pdf_path": "references/R001/nonexistent.pdf",
                                        "reference_folder_path": "references/R001",
                                    },
                                    "match_confidence": "high",
                                    "alternative_candidates": [],
                                    "failure_reason": "",
                                    "notes": [],
                                }
                            ]
                            payload["reference_index"] = entries
                            injected_entry = True
                        else:
                            first = entries[0]
                            first["retrieval_status"] = "retrieved"
                            first["match_confidence"] = "high"
                            first["matched_record"] = {
                                "title": "Synthetic Retrieved Ref",
                                "authors": ["A. Author"],
                                "year": "2023",
                                "source": "arxiv",
                                "url": "https://arxiv.org/abs/2303.10130",
                                "pdf_path": "references/R001/nonexistent.pdf",
                                "reference_folder_path": "references/R001",
                            }
                            first["failure_reason"] = ""
                        payload["retrieval_summary"] = {
                            "total_references": len(entries),
                            "retrieved_count": 1 if entries else 0,
                            "ambiguous_count": 0,
                            "not_found_count": max(0, len(entries) - (1 if entries else 0)),
                            "warnings": [],
                        }

                        if injected_entry:
                            responses.insert(
                                idx + 1,
                                {
                                    "reference_id": "R001",
                                    "reference_title": "Synthetic Retrieved Ref",
                                    "summary": {
                                        "main_topic": "Synthetic",
                                        "main_contribution": "Synthetic",
                                        "brief_summary": "Synthetic summary for e2e sequencing.",
                                    },
                                    "relation_to_source_paper": {
                                        "relation_type": ["background_context"],
                                        "description": "Synthetic relation.",
                                        "importance_for_source_presentation": "low",
                                    },
                                    "useful_points_for_main_presentation": [],
                                    "possible_useful_artifacts": [],
                                    "mention_recommendation": {
                                        "should_mention_in_final_deck": False,
                                        "recommended_scope": "none",
                                        "rationale": "Synthetic test entry.",
                                    },
                                    "warnings": [],
                                    "confidence": "low",
                                },
                            )
                        break
                return responses

            with patch.dict(os.environ, {"USE_MOCK_LLM": "true"}, clear=False):
                with patch("app.orchestrator.workflow._build_fake_responses", side_effect=_patched_fake_responses):
                    run_output = workflow_module.run_workflow(pdf_path=pdf_path, repair_on_audit=False)

            run_path = Path(run_output["summary"]["run_path"])
            index_path = run_path / "references" / "reference_index.json"
            self.assertTrue(index_path.is_file())

            payload = json.loads(index_path.read_text(encoding="utf-8"))
            entries = payload.get("reference_index", [])
            self.assertTrue(entries)

            # Invariant: every entry marked retrieved must point to a real PDF file.
            for entry in entries:
                if entry.get("retrieval_status") != "retrieved":
                    continue
                pdf_raw = str((entry.get("matched_record") or {}).get("pdf_path", "")).strip()
                self.assertTrue(pdf_raw, "retrieved entry is missing matched_record.pdf_path")
                pdf_candidate = Path(pdf_raw)
                if not pdf_candidate.is_absolute():
                    pdf_candidate = (run_path / pdf_candidate).resolve()
                self.assertTrue(pdf_candidate.is_file(), f"retrieved entry points to missing file: {pdf_candidate}")
                self.assertEqual(pdf_candidate.suffix.lower(), ".pdf")

    @staticmethod
    def _write_minimal_pdf(path: Path) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        with path.open("wb") as handle:
            writer.write(handle)


if __name__ == "__main__":
    unittest.main()
