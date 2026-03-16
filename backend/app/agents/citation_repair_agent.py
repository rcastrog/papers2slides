"""Targeted repair agent wrapper for citation issues."""

from app.agents.base_agent import BaseAgent
from app.models.repair_result import RepairResult


class CitationRepairAgent(BaseAgent[RepairResult]):
    """Repair missing/weak/misaligned citation mappings."""

    prompt_file = "repair_citation.txt"
    output_model = RepairResult
