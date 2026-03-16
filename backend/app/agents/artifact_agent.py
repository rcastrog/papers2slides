"""Agent for extracting and evaluating visual/text artifacts."""

from app.agents.base_agent import BaseAgent
from app.models.artifact_manifest import ArtifactManifest


class ArtifactExtractionAgent(BaseAgent[ArtifactManifest]):
	"""A3 concrete agent for artifact extraction and triage."""

	prompt_file = "A3_artifact_extraction.txt"
	output_model = ArtifactManifest


class ArtifactAgent(ArtifactExtractionAgent):
	"""Backward-compatible alias while the codebase migrates naming."""
