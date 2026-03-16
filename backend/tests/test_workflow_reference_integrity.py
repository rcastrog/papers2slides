"""Integration-style tests for A4 retrieval artifact integrity enforcement."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.reference_index import ReferenceIndex
from app.orchestrator.workflow import (
    _build_retrieval_candidates,
    _enforce_reference_retrieval_integrity,
    _ensure_reference_index_coverage,
    _recover_references_deterministically,
    _promote_reference_retrieval_from_identifiers,
    _run_reference_retrieval_with_batches,
)


class FakeArxivClient:
    """Simple deterministic client used to emulate arXiv download metadata."""

    @staticmethod
    def extract_arxiv_id(text: str | None) -> str:
        if not text:
            return ""
        match = re.search(r"([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", str(text))
        return match.group(1) if match else ""

    def __init__(self, source_pdf_uri: str) -> None:
        self._source_pdf_uri = source_pdf_uri

    def get_by_id(self, arxiv_id: str) -> dict[str, object] | None:
        normalized = self.extract_arxiv_id(arxiv_id)
        if not normalized:
            return None
        return {
            "title": "Downloaded Reference",
            "authors": ["A. Author"],
            "year": "2024",
            "source": "arxiv",
            "url": f"https://arxiv.org/abs/{normalized}",
            "pdf_url": self._source_pdf_uri,
            "arxiv_id": normalized,
        }

    def search(self, query: str, max_results: int = 1) -> list[dict[str, object]]:
        _ = (query, max_results)
        return []


def _build_reference_index(*, retrieval_status: str, pdf_path: str, url: str = "") -> ReferenceIndex:
    return ReferenceIndex.model_validate(
        {
            "reference_index": [
                {
                    "reference_id": "R001",
                    "original_reference_text": "[1] Test reference",
                    "parsed_reference": {
                        "title": "Test Reference",
                        "authors": ["A. Author"],
                        "venue_or_source": "arXiv",
                        "year": "2024",
                        "arxiv_id": "2303.10130",
                        "doi": "",
                    },
                    "parsing_confidence": "high",
                    "retrieval_status": retrieval_status,
                    "matched_record": {
                        "title": "Test Reference",
                        "authors": ["A. Author"],
                        "year": "2024",
                        "source": "arxiv",
                        "url": url,
                        "pdf_path": pdf_path,
                        "reference_folder_path": "",
                    },
                    "match_confidence": "high",
                    "alternative_candidates": [],
                    "failure_reason": "",
                    "notes": [],
                }
            ],
            "retrieval_summary": {
                "total_references": 1,
                "retrieved_count": 1 if retrieval_status == "retrieved" else 0,
                "ambiguous_count": 0,
                "not_found_count": 0 if retrieval_status == "retrieved" else 1,
                "warnings": [],
            },
        }
    )


class WorkflowReferenceIntegrityTests(unittest.TestCase):
    def test_build_retrieval_candidates_uses_author_title_fallback_queries(self) -> None:
        class QueryAwareClient:
            def __init__(self) -> None:
                self.queries: list[str] = []

            def search(self, query: str, max_results: int = 2) -> list[dict[str, object]]:
                _ = max_results
                self.queries.append(query)
                if "Chris Dyer" in query:
                    return [
                        {
                            "title": "Recurrent Neural Network Grammars",
                            "authors": ["Chris Dyer"],
                            "year": "2016",
                            "source": "arxiv",
                            "url": "https://arxiv.org/abs/1602.07776",
                            "pdf_url": "https://arxiv.org/pdf/1602.07776.pdf",
                            "arxiv_id": "1602.07776",
                        }
                    ]
                return []

            def get_by_id(self, arxiv_id: str) -> dict[str, object] | None:
                _ = arxiv_id
                return None

        client = QueryAwareClient()
        references = [
            "[8] Chris Dyer, Adhiguna Kuncoro, Miguel Ballesteros, and Noah A. Smith. Recurrent neural network grammars. In Proc. of NAACL, 2016."
        ]

        candidates = _build_retrieval_candidates(references, client)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["arxiv_candidates"]), 1)
        self.assertTrue(any("Recurrent neural network grammars" in q for q in client.queries))
        self.assertTrue(any("Chris Dyer" in q for q in client.queries))

    def test_build_retrieval_candidates_deduplicates_multi_query_hits(self) -> None:
        class DuplicateResultClient:
            def search(self, query: str, max_results: int = 2) -> list[dict[str, object]]:
                _ = (query, max_results)
                return [
                    {
                        "title": "Test",
                        "authors": ["A. Author"],
                        "year": "2024",
                        "source": "arxiv",
                        "url": "https://arxiv.org/abs/2303.10130",
                        "pdf_url": "https://arxiv.org/pdf/2303.10130.pdf",
                        "arxiv_id": "2303.10130",
                    }
                ]

            def get_by_id(self, arxiv_id: str) -> dict[str, object] | None:
                _ = arxiv_id
                return None

        candidates = _build_retrieval_candidates(
            ["A. Author. Test reference title. Conference, 2024."],
            DuplicateResultClient(),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["arxiv_candidates"]), 1)

    def test_build_retrieval_candidates_uses_openalex_fallback_when_arxiv_empty(self) -> None:
        class EmptyArxivClient:
            def search(self, query: str, max_results: int = 2) -> list[dict[str, object]]:
                _ = (query, max_results)
                return []

            def get_by_id(self, arxiv_id: str) -> dict[str, object] | None:
                _ = arxiv_id
                return None

        fake_openalex_payload = {
            "results": [
                {
                    "display_name": "Recurrent Neural Network Grammars",
                    "publication_year": 2016,
                    "doi": "https://doi.org/10.18653/v1/N16-1024",
                    "authorships": [
                        {"author": {"display_name": "Chris Dyer"}},
                        {"author": {"display_name": "Noah A. Smith"}},
                    ],
                    "open_access": {"oa_url": "https://example.org/rnng.pdf"},
                }
            ]
        }

        with patch("app.orchestrator.workflow._fetch_openalex_json", return_value=fake_openalex_payload):
            candidates = _build_retrieval_candidates(
                ["Chris Dyer et al. Recurrent neural network grammars. NAACL, 2016."],
                EmptyArxivClient(),
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["arxiv_candidates"]), 1)
        self.assertEqual(candidates[0]["arxiv_candidates"][0]["source"], "doi")
        self.assertIn("10.18653", candidates[0]["arxiv_candidates"][0]["url"])

    def test_batched_a4_merges_entries_from_multiple_calls(self) -> None:
        class FakeBatchAgent:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def run(self, input_payload: dict[str, object]) -> ReferenceIndex:
                refs = list(input_payload.get("references_raw", []))
                self.calls.append(refs)
                start_id = 1
                entries = []
                for idx, ref in enumerate(refs, start=start_id):
                    entries.append(
                        {
                            "reference_id": f"R{idx:03d}",
                            "original_reference_text": ref,
                            "parsed_reference": {
                                "title": f"Title {ref}",
                                "authors": ["A. Author"],
                                "venue_or_source": "arXiv",
                                "year": "2024",
                                "arxiv_id": "",
                                "doi": "",
                            },
                            "parsing_confidence": "medium",
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
                    )
                return ReferenceIndex.model_validate(
                    {
                        "reference_index": entries,
                        "retrieval_summary": {
                            "total_references": len(entries),
                            "retrieved_count": 0,
                            "ambiguous_count": 0,
                            "not_found_count": len(entries),
                            "warnings": [],
                        },
                    }
                )

        references_raw = [f"Reference {idx}" for idx in range(1, 26)]
        agent = FakeBatchAgent()
        stage_entry = {"warnings": []}

        result = _run_reference_retrieval_with_batches(
            reference_retrieval_agent=agent,
            stage_entry=stage_entry,
            job_spec_payload={},
            source_metadata_payload={},
            references_raw=references_raw,
            reference_parse_warnings=[],
            retrieval_candidates=[{"reference_text": ref, "arxiv_candidates": []} for ref in references_raw],
        )

        self.assertEqual(len(agent.calls), 3)
        self.assertEqual(len(result.reference_index), 25)
        self.assertEqual(result.reference_index[0].reference_id, "R001")
        self.assertEqual(result.reference_index[-1].reference_id, "R025")
        self.assertIn("A4 batched retrieval enabled", " ".join(result.retrieval_summary.warnings))

    def test_batched_a4_continues_when_one_batch_fails(self) -> None:
        class FlakyBatchAgent:
            def __init__(self) -> None:
                self.call_count = 0

            def run(self, input_payload: dict[str, object]) -> ReferenceIndex:
                self.call_count += 1
                if self.call_count == 2:
                    raise ValueError("simulated second-batch failure")
                refs = list(input_payload.get("references_raw", []))
                entries = []
                for idx, ref in enumerate(refs, start=1):
                    entries.append(
                        {
                            "reference_id": f"R{idx:03d}",
                            "original_reference_text": ref,
                            "parsed_reference": {
                                "title": ref,
                                "authors": ["A. Author"],
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
                    )
                return ReferenceIndex.model_validate(
                    {
                        "reference_index": entries,
                        "retrieval_summary": {
                            "total_references": len(entries),
                            "retrieved_count": 0,
                            "ambiguous_count": 0,
                            "not_found_count": len(entries),
                            "warnings": [],
                        },
                    }
                )

        references_raw = [f"Reference {idx}" for idx in range(1, 26)]
        stage_entry = {"warnings": []}

        result = _run_reference_retrieval_with_batches(
            reference_retrieval_agent=FlakyBatchAgent(),
            stage_entry=stage_entry,
            job_spec_payload={},
            source_metadata_payload={},
            references_raw=references_raw,
            reference_parse_warnings=[],
            retrieval_candidates=[{"reference_text": ref, "arxiv_candidates": []} for ref in references_raw],
        )

        self.assertEqual(len(result.reference_index), 13)
        self.assertTrue(any("failed" in warning.lower() for warning in result.retrieval_summary.warnings))
        self.assertTrue(any("failed" in warning.lower() for warning in stage_entry["warnings"]))

    def test_coverage_guard_synthesizes_missing_reference_entries(self) -> None:
        index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "First reference",
                        "parsed_reference": {
                            "title": "First",
                            "authors": ["A. Author"],
                            "venue_or_source": "arXiv",
                            "year": "2024",
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

        updated, warnings = _ensure_reference_index_coverage(
            reference_index=index,
            references_raw=["First reference", "Second reference", "Third reference"],
        )

        self.assertEqual(len(updated.reference_index), 3)
        self.assertEqual([entry.reference_id for entry in updated.reference_index], ["R001", "R002", "R003"])
        self.assertEqual(updated.retrieval_summary.total_references, 3)
        self.assertEqual(updated.retrieval_summary.not_found_count, 3)
        self.assertTrue(warnings)

    def test_downgrades_retrieved_when_pdf_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir) / "run"
            run_path.mkdir(parents=True, exist_ok=True)

            index = _build_reference_index(
                retrieval_status="retrieved",
                pdf_path=str(run_path / "references" / "R001" / "missing.pdf"),
                url="https://arxiv.org/abs/2303.10130",
            )

            with patch("app.orchestrator.workflow._download_pdf_file", return_value=None):
                updated, warnings = _enforce_reference_retrieval_integrity(
                    reference_index=index,
                    run_path=run_path,
                    arxiv_client=None,
                )

            self.assertEqual(updated.reference_index[0].retrieval_status, "not_found")
            self.assertEqual(updated.retrieval_summary.retrieved_count, 0)
            self.assertEqual(updated.retrieval_summary.not_found_count, 1)
            self.assertTrue(warnings)

    def test_promotes_not_found_with_parsed_arxiv_id(self) -> None:
        index = _build_reference_index(
            retrieval_status="not_found",
            pdf_path="",
            url="",
        )

        updated, warnings = _promote_reference_retrieval_from_identifiers(
            reference_index=index,
            arxiv_client=None,
        )

        self.assertEqual(updated.reference_index[0].retrieval_status, "retrieved")
        self.assertEqual(updated.reference_index[0].matched_record.source, "arxiv")
        self.assertIn("arxiv.org/abs/2303.10130", updated.reference_index[0].matched_record.url)
        self.assertEqual(updated.retrieval_summary.retrieved_count, 1)
        self.assertTrue(warnings)

    def test_backfill_extracts_single_author_and_title_after_author_sentence(self) -> None:
        index = ReferenceIndex.model_validate(
            {
                "reference_index": [
                    {
                        "reference_id": "R001",
                        "original_reference_text": "[1] Francois Chollet. Xception: Deep learning with depthwise separable convolutions. arXiv preprint arXiv:1610.02357, 2016.",
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
            reference_index=index,
            references_raw=[
                "[1] Francois Chollet. Xception: Deep learning with depthwise separable convolutions. arXiv preprint arXiv:1610.02357, 2016."
            ],
        )

        parsed = updated.reference_index[0].parsed_reference
        self.assertEqual(parsed.title, "Xception: Deep learning with depthwise separable convolutions")
        self.assertIn("Francois Chollet", parsed.authors)
        self.assertEqual(parsed.arxiv_id, "1610.02357")

    def test_keeps_retrieved_when_pdf_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir) / "run"
            reference_dir = run_path / "references" / "R001"
            reference_dir.mkdir(parents=True, exist_ok=True)
            existing_pdf = reference_dir / "local.pdf"
            existing_pdf.write_bytes(b"%PDF-1.4\nexisting")

            index = _build_reference_index(
                retrieval_status="retrieved",
                pdf_path=str(existing_pdf),
                url="https://arxiv.org/abs/2303.10130",
            )

            updated, warnings = _enforce_reference_retrieval_integrity(
                reference_index=index,
                run_path=run_path,
                arxiv_client=None,
            )

            self.assertEqual(updated.reference_index[0].retrieval_status, "retrieved")
            self.assertEqual(Path(updated.reference_index[0].matched_record.pdf_path), existing_pdf)
            self.assertEqual(updated.retrieval_summary.retrieved_count, 1)
            self.assertFalse(warnings)

    def test_downloads_pdf_when_arxiv_metadata_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_path = root / "run"
            run_path.mkdir(parents=True, exist_ok=True)

            source_pdf = root / "source.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\ndownloaded")
            fake_client = FakeArxivClient(source_pdf.as_uri())

            index = _build_reference_index(
                retrieval_status="retrieved",
                pdf_path="",
                url="https://arxiv.org/abs/2303.10130",
            )

            updated, warnings = _enforce_reference_retrieval_integrity(
                reference_index=index,
                run_path=run_path,
                arxiv_client=fake_client,
            )

            persisted_path = Path(updated.reference_index[0].matched_record.pdf_path)
            self.assertEqual(updated.reference_index[0].retrieval_status, "retrieved")
            self.assertTrue(persisted_path.is_file())
            self.assertGreater(persisted_path.stat().st_size, 0)
            self.assertFalse(warnings)

    def test_downloads_pdf_via_doi_open_access_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_path = root / "run"
            run_path.mkdir(parents=True, exist_ok=True)

            source_pdf = root / "doi-source.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\nopen-access")

            index = ReferenceIndex.model_validate(
                {
                    "reference_index": [
                        {
                            "reference_id": "R001",
                            "original_reference_text": "Sample paper DOI 10.1000/xyz123",
                            "parsed_reference": {
                                "title": "Sample DOI Reference",
                                "authors": ["A. Author"],
                                "venue_or_source": "Journal",
                                "year": "2024",
                                "arxiv_id": "",
                                "doi": "10.1000/xyz123",
                            },
                            "parsing_confidence": "high",
                            "retrieval_status": "retrieved",
                            "matched_record": {
                                "title": "",
                                "authors": [],
                                "year": "",
                                "source": "other",
                                "url": "",
                                "pdf_path": "",
                                "reference_folder_path": "",
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

            with patch(
                "app.orchestrator.workflow._lookup_open_access_pdf",
                return_value=(source_pdf.as_uri(), "doi", "https://doi.org/10.1000/xyz123"),
            ):
                updated, warnings = _enforce_reference_retrieval_integrity(
                    reference_index=index,
                    run_path=run_path,
                    arxiv_client=None,
                )

            persisted_path = Path(updated.reference_index[0].matched_record.pdf_path)
            self.assertEqual(updated.reference_index[0].retrieval_status, "retrieved")
            self.assertEqual(updated.reference_index[0].matched_record.source, "doi")
            self.assertTrue(persisted_path.is_file())
            self.assertGreater(persisted_path.stat().st_size, 0)
            self.assertEqual(updated.retrieval_summary.retrieved_count, 1)
            self.assertFalse(warnings)

    def test_deterministic_recovery_promotes_not_found_when_pdf_download_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir) / "run"
            run_path.mkdir(parents=True, exist_ok=True)

            source_pdf = Path(temp_dir) / "deterministic-source.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\ndeterministic")

            index = _build_reference_index(
                retrieval_status="not_found",
                pdf_path="",
                url="https://arxiv.org/abs/2303.10130",
            )

            with patch(
                "app.orchestrator.workflow._lookup_open_access_pdf",
                return_value=(source_pdf.as_uri(), "doi", "https://doi.org/10.1000/xyz123"),
            ):
                updated, warnings = _recover_references_deterministically(
                    reference_index=index,
                    run_path=run_path,
                    arxiv_client=None,
                )

            entry = updated.reference_index[0]
            self.assertEqual(entry.retrieval_status, "retrieved")
            self.assertTrue(Path(entry.matched_record.pdf_path).is_file())
            self.assertEqual(updated.retrieval_summary.retrieved_count, 1)
            self.assertTrue(any("Deterministic retrieval attempted" in warning for warning in warnings))

    def test_deterministic_recovery_keeps_not_found_when_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir) / "run"
            run_path.mkdir(parents=True, exist_ok=True)

            index = _build_reference_index(
                retrieval_status="not_found",
                pdf_path="",
                url="",
            )

            with patch("app.orchestrator.workflow._download_pdf_file", return_value=None):
                updated, warnings = _recover_references_deterministically(
                    reference_index=index,
                    run_path=run_path,
                    arxiv_client=None,
                )

            self.assertEqual(updated.reference_index[0].retrieval_status, "not_found")
            self.assertEqual(updated.retrieval_summary.retrieved_count, 0)
            self.assertTrue(any("Deterministic retrieval attempted" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
