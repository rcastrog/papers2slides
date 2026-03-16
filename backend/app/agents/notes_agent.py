"""Agent for generating speaker notes from a presentation plan."""

from app.agents.base_agent import BaseAgent
from app.models.speaker_notes import SpeakerNotes


class SpeakerNotesAgent(BaseAgent[SpeakerNotes]):
    """A7 concrete agent for concise per-slide speaker notes."""

    prompt_file = "A7_speaker_notes.txt"
    output_model = SpeakerNotes
