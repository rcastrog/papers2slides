"""Targeted repair agent wrapper for speaker-note issues."""

from app.agents.base_agent import BaseAgent
from app.models.repair_result import RepairResult


class NotesRepairAgent(BaseAgent[RepairResult]):
    """Repair unsupported or drifting speaker notes."""

    prompt_file = "repair_notes.txt"
    output_model = RepairResult
