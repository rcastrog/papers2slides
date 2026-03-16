"""Targeted repair agent wrapper for risky visual assignments."""

from app.agents.base_agent import BaseAgent
from app.models.repair_result import RepairResult


class VisualRepairAgent(BaseAgent[RepairResult]):
    """Repair visual overreach/distortion/provenance issues."""

    prompt_file = "repair_visual.txt"
    output_model = RepairResult
