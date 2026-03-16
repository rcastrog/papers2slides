"""Agent for retrieving and indexing references from bibliography input."""

from app.agents.base_agent import BaseAgent
from app.models.reference_index import ReferenceIndex


class ReferenceRetrievalAgent(BaseAgent[ReferenceIndex]):
	"""A4 concrete agent for reference retrieval/indexing."""

	prompt_file = "A4_reference_retrieval.txt"
	output_model = ReferenceIndex
