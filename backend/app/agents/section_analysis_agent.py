"""Agent for section-level analysis and extraction."""

from app.agents.base_agent import BaseAgent
from app.models.section_analysis import SectionAnalysisResult


class SectionAnalysisAgent(BaseAgent[SectionAnalysisResult]):
    prompt_file = "A2_section_analysis.txt"
    output_model = SectionAnalysisResult
