"""Smoke test for IntakeAgent using a fake LLM transport."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.intake_agent import IntakeAgent
from app.config import LLMSettings
from app.services.llm_client import LLMClient, OpenAIChatTransport, SequentialMockTransport
from app.services.prompt_loader import PromptLoader


def _intake_payload() -> dict[str, object]:
    return {
        "job_id": "job-test-001",
        "source": {"source_type": "local_pdf", "source_value": "papers/test.pdf"},
        "presentation_style": "journal_club",
        "target_audience": "research_specialists",
        "language": "en",
        "output_formats": ["reveal"],
        "target_duration_minutes": 20,
        "target_slide_count": 12,
        "automation_mode": "checkpointed",
        "approval_checkpoints_enabled": True,
        "checkpoints": ["parse_summary", "presentation_plan"],
        "reference_mode": "retrieve_all_light_summarize",
        "visual_policy": "balanced",
        "equation_policy": "avoid_unless_essential",
        "citation_style": "APA",
        "speaker_notes_style": "brief_talking_points",
        "user_notes": [],
        "defaults_applied": [],
        "warnings": [],
        "validation_errors": [],
    }


class IntakeAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_jobspec(self) -> None:
        llm_client = LLMClient(transport=SequentialMockTransport([_intake_payload()]))
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = IntakeAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        sample_input = {
            "source": {"source_type": "local_pdf", "source_value": "papers/test.pdf"},
            "presentation_style": "journal_club",
            "language": "en",
        }

        result = agent.run(sample_input)

        self.assertEqual(result.language, "en")
        self.assertEqual(result.source.source_type, "local_pdf")
        self.assertEqual(result.presentation_style, "journal_club")

    @unittest.skipUnless(os.getenv("PAPER2SLIDES_REAL_LLM_SMOKE") == "1", "Set PAPER2SLIDES_REAL_LLM_SMOKE=1 to enable")
    def test_real_openai_smoke_json_contract(self) -> None:
        settings = LLMSettings.from_env()
        if settings.provider != "openai" or not settings.has_openai_config:
            self.skipTest("Real OpenAI config is not available")

        transport = OpenAIChatTransport(
            api_key=settings.openai_api_key,
            default_model=settings.llm_model,
            base_url=settings.openai_base_url,
            temperature=0.0,
            timeout_seconds=settings.openai_timeout_seconds,
        )
        llm_client = LLMClient(transport=transport, default_model=settings.llm_model)

        response_text = llm_client.generate(
            "Return a JSON object with keys: status and provider.",
            {"status": "ok", "provider": "openai"},
        )
        payload = json.loads(response_text)

        self.assertIsInstance(payload, dict)
        self.assertIn("status", payload)


if __name__ == "__main__":
    unittest.main()
