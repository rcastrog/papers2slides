"""Smoke test for NotesRepairAgent."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.notes_repair_agent import NotesRepairAgent
from app.models.repair_result import RepairResult
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "repair_status": "applied",
                "target_ids": ["slide_note_1"],
                "changes_made": ["Trimmed note verbosity"],
                "unresolved_risks": [],
                "repair_confidence": "medium",
                "warnings": [],
            }
        )


class NotesRepairAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_repair_result(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = NotesRepairAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"audit_findings": []})

        self.assertIsInstance(result, RepairResult)
        self.assertEqual(result.repair_status, "applied")


if __name__ == "__main__":
    unittest.main()
