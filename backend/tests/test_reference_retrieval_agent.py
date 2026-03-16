"""Smoke test for ReferenceRetrievalAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.reference_retrieval_agent import ReferenceRetrievalAgent
from app.models.reference_index import ReferenceIndex
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    """Returns deterministic A4 JSON payload for smoke testing."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "reference_index": [
                {
                    "reference_id": "R001",
                    "original_reference_text": "[1] Test reference",
                    "parsed_reference": {
                        "title": "Test Reference",
                        "authors": ["A. Author"],
                        "venue_or_source": "arXiv",
                        "year": "2023",
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
                    "failure_reason": "Stubbed retrieval",
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
        return json.dumps(payload)


class FakeTransportNullables:
    """Returns deterministic A4 payload with nullable fields seen in real runs."""

    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        payload = {
            "reference_index": [
                {
                    "reference_id": "R001",
                    "original_reference_text": "[1] Test reference",
                    "parsed_reference": {
                        "title": "Test Reference",
                        "authors": ["A. Author"],
                        "venue_or_source": None,
                        "year": "2023",
                        "arxiv_id": None,
                        "doi": None,
                    },
                    "parsing_confidence": "medium",
                    "retrieval_status": "not_found",
                    "matched_record": None,
                    "match_confidence": None,
                    "alternative_candidates": None,
                    "failure_reason": None,
                    "notes": None,
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
        return json.dumps(payload)


class ReferenceRetrievalAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_reference_index(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ReferenceRetrievalAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"references_raw": ["[1] Test reference"]})

        self.assertIsInstance(result, ReferenceIndex)
        self.assertEqual(result.retrieval_summary.total_references, 1)

    def test_run_coerces_nullable_reference_fields(self) -> None:
        llm_client = LLMClient(transport=FakeTransportNullables())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = ReferenceRetrievalAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"references_raw": ["[1] Test reference"]})

        self.assertIsInstance(result, ReferenceIndex)
        entry = result.reference_index[0]
        self.assertEqual(entry.parsed_reference.arxiv_id, "")
        self.assertEqual(entry.parsed_reference.doi, "")
        self.assertEqual(entry.match_confidence, "low")
        self.assertEqual(entry.matched_record.source, "other")


if __name__ == "__main__":
    unittest.main()
