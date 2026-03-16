"""Agent for generating the slide-level presentation plan."""

from app.agents.base_agent import BaseAgent
from app.models.presentation_plan import PresentationPlan


class PresentationPlannerAgent(BaseAgent[PresentationPlan]):
	"""A6 concrete agent that produces a validated deck plan."""

	prompt_file = "A6_presentation_planner.txt"
	output_model = PresentationPlan


class PlannerAgent(PresentationPlannerAgent):
	"""Backward-compatible alias while callers migrate names."""
