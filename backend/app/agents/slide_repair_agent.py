"""Targeted repair agent wrapper for slide-level issues."""

from app.agents.base_agent import BaseAgent
from app.models.repair_result import RepairResult


class SlideRepairAgent(BaseAgent[RepairResult]):
    """Repair unsupported/overclaiming slide content conservatively."""

    prompt_file = "repair_slide.txt"
    output_model = RepairResult
