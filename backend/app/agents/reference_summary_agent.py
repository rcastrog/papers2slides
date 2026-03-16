"""Agent for lightweight per-reference summarization."""

from app.agents.base_agent import BaseAgent
from app.models.reference_summary import ReferenceSummary


class ReferenceSummaryAgent(BaseAgent[ReferenceSummary]):
	"""A5 concrete agent for one-reference light summaries."""

	prompt_file = "A5_reference_light_summary.txt"
	output_model = ReferenceSummary
