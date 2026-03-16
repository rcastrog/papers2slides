"""Targeted repair agent wrapper for translation drift issues."""

from app.agents.base_agent import BaseAgent
from app.models.repair_result import RepairResult


class TranslationRepairAgent(BaseAgent[RepairResult]):
    """Repair translation fidelity and tone drift issues conservatively."""

    prompt_file = "repair_translation.txt"
    output_model = RepairResult
