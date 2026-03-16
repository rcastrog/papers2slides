"""Smoke test for SpeakerNotesAgent with mocked LLM output."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.notes_agent import SpeakerNotesAgent
from app.models.speaker_notes import SpeakerNotes
from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader


class FakeTransport:
    def complete(self, system_prompt: str, input_payload: dict, model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        return json.dumps(
            {
                "deck_language": "en",
                "notes_style": "brief_talking_points",
                "slide_notes": [
                    {
                        "slide_number": 1,
                        "slide_title": "Slide 1",
                        "talking_points": ["Point A", "Point B"],
                        "timing_hint_seconds": 60,
                        "caution_notes": [],
                    }
                ],
                "global_notes_warnings": [],
            }
        )


class NotesAgentSmokeTest(unittest.TestCase):
    def test_run_returns_validated_speaker_notes(self) -> None:
        llm_client = LLMClient(transport=FakeTransport())
        prompt_loader = PromptLoader(prompts_dir=PROJECT_ROOT / "backend" / "app" / "prompts")
        agent = SpeakerNotesAgent(llm_client=llm_client, prompt_loader=prompt_loader)

        result = agent.run({"presentation_plan": {"slides": []}})

        self.assertIsInstance(result, SpeakerNotes)
        self.assertEqual(result.slide_notes[0].slide_number, 1)


if __name__ == "__main__":
    unittest.main()
