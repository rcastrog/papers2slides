"""Smoke test for ParserAgent with mocked LLM output."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.parser_agent import ParserAgent
from app.models.parse_result import PaperParseResult
from app.services.llm_client import LLMClient, SequentialMockTransport
from app.services.prompt_loader import PromptLoader
from app.storage.run_manager import RunManager


def _parser_payload() -> dict[str, object]:
    return {
        "source_status": {
            "acquired": True,
            "source_type": "local_pdf",
            "source_value": "papers/test.pdf",
            "stored_pdf_path": "runs/sample/source_paper/paper.pdf",
            "notes": [],
        },
        "metadata": {
            "title": "Test Paper",
            "authors": ["A. Researcher", "B. Scientist"],
            "venue_or_source": "arXiv",
            "year": "2024",
            "abstract": "A short abstract.",
            "keywords": ["llm", "slides"],
            "metadata_confidence": "high",
            "inferred_fields": [],
        },
        "section_index": [
            {
                "section_id": "s1",
                "section_title": "Introduction",
                "section_level": 1,
                "page_start": 1,
                "page_end": 2,
                "order": 1,
                "is_inferred_boundary": False,
                "text_path": "runs/sample/analysis/sections/s1.txt",
            }
        ],
        "full_text_path": "runs/sample/analysis/full_text.txt",
        "bibliography": {
            "detected": True,
            "references_count": 12,
            "references_raw_path": "runs/sample/references/raw_refs.txt",
            "extraction_confidence": "medium",
        },
        "parse_quality": {
            "ocr_used": False,
            "missing_pages": [],
            "garbled_regions": [],
            "suspected_parsing_issues": [],
            "warnings": [],
            "overall_confidence": "high",
        },
    }


class ParserAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_parse_result_and_persists_artifacts(self) -> None:
        llm_client = LLMClient(transport=SequentialMockTransport([_parser_payload()]))
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")

        with tempfile.TemporaryDirectory() as tmpdir:
            run_manager = RunManager(runs_root=Path(tmpdir) / "runs")
            run_path = run_manager.create_run(slug="parser-smoke")

            agent = ParserAgent(
                llm_client=llm_client,
                prompt_loader=prompt_loader,
                run_manager=run_manager,
            )

            sample_input = {
                "job_spec": {"job_id": "job-test-001"},
                "paper_source": {
                    "source_type": "local_pdf",
                    "source_value": "papers/test.pdf",
                },
            }

            result = agent.run(
                sample_input,
                pdf_path="papers/test.pdf",
                extracted_text_payload={
                    "pdf_path": "papers/test.pdf",
                    "page_count": 2,
                    "warnings": [],
                    "combined_text": "Intro text",
                },
                section_candidates=[
                    {
                        "section_title": "Introduction",
                        "start_index": 0,
                        "end_index": 12,
                        "text": "Intro text",
                        "confidence": 0.9,
                        "inferred": False,
                    }
                ],
            )

            self.assertIsInstance(result, PaperParseResult)
            self.assertEqual(result.source_status.source_type, "local_pdf")

            raw_path = run_path / "analysis" / "ParserAgent_raw.txt"
            validated_path = run_path / "analysis" / "ParserAgent_validated.json"
            self.assertTrue(raw_path.is_file())
            self.assertTrue(validated_path.is_file())


if __name__ == "__main__":
    unittest.main()
