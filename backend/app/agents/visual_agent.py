"""Agent for generating structured visual specifications."""

from app.agents.base_agent import BaseAgent
from app.models.generated_visuals import GeneratedVisuals


class VisualGenerationAgent(BaseAgent[GeneratedVisuals]):
    """A8 concrete agent for visual specs and generation prompts."""

    prompt_file = "A8_visual_generation.txt"
    output_model = GeneratedVisuals
