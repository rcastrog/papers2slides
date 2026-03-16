"""Pydantic model for section analysis outputs."""

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SectionClaim(BaseModel):
	model_config = ConfigDict(extra="forbid")

	claim: str
	support_level_within_section: Literal["strong", "moderate", "weak"]
	notes: str


class ConceptNeedingExplanation(BaseModel):
	model_config = ConfigDict(extra="forbid")

	concept: str
	reason: Literal["jargon", "prerequisite", "non-intuitive mechanism", "dense wording"]
	importance: Literal["high", "medium", "low"]


class EvidenceOrArgument(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"experiment": "experiment",
		"empirical": "experiment",
		"reasoning": "reasoning",
		"argument": "reasoning",
		"comparison": "comparison",
		"ablation": "ablation",
		"theoretical argument": "theoretical_argument",
		"theoretical_argument": "theoretical_argument",
		"theory": "theoretical_argument",
		"dataset description": "dataset_description",
		"dataset_description": "dataset_description",
		"data": "dataset_description",
		"method explanation": "other",
		"method_explanation": "other",
		"method": "other",
		"visualization": "other",
		"visualisation": "other",
		"other": "other",
	}

	type: Literal[
		"experiment",
		"reasoning",
		"comparison",
		"ablation",
		"theoretical_argument",
		"dataset_description",
		"other",
	]
	description: str

	@field_validator("type", mode="before")
	@classmethod
	def _coerce_type(cls, value: Any) -> Any:
		if value is None:
			return "other"
		candidate = str(value).strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		mapped = cls._TYPE_ALIASES.get(alias_key)
		if mapped:
			return mapped
		return "other"


class CandidateVisualizableIdea(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_VISUAL_TYPE_HINT_ALIASES: ClassVar[dict[str, str]] = {
		"process diagram": "process_diagram",
		"process_diagram": "process_diagram",
		"workflow": "process_diagram",
		"pipeline": "process_diagram",
		"comparison table": "comparison_table",
		"comparison_table": "comparison_table",
		"table": "comparison_table",
		"flow": "flow",
		"flowchart": "flow",
		"flow chart": "flow",
		"conceptual figure": "conceptual_figure",
		"conceptual_figure": "conceptual_figure",
		"concept map": "conceptual_figure",
		"timeline": "timeline",
		"bar chart": "other",
		"bar_chart": "other",
		"line chart": "other",
		"line_chart": "other",
		"scatter plot": "other",
		"scatter_plot": "other",
		"chart": "other",
		"plot": "other",
		"other": "other",
	}

	idea: str
	visual_type_hint: Literal[
		"process_diagram",
		"comparison_table",
		"flow",
		"conceptual_figure",
		"timeline",
		"other",
	]
	source_support: Literal["direct", "inferred_from_section_structure"]

	@field_validator("visual_type_hint", mode="before")
	@classmethod
	def _coerce_visual_type_hint(cls, value: Any) -> Any:
		if value is None:
			return "other"
		candidate = str(value).strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		mapped = cls._VISUAL_TYPE_HINT_ALIASES.get(alias_key)
		if mapped:
			return mapped

		if any(token in alias_key for token in ("bar", "line", "scatter", "chart", "plot")):
			return "other"

		return "other"


class PresentationRelevance(BaseModel):
	model_config = ConfigDict(extra="forbid")

	importance_for_final_deck: Literal["high", "medium", "low"]
	why_it_matters: str
	likely_slide_use: list[Literal["main_content", "supporting_context"]] = Field(min_length=1)

	@field_validator("likely_slide_use", mode="before")
	@classmethod
	def _coerce_likely_slide_use(cls, value: Any) -> Any:
		if value is None:
			return ["supporting_context"]
		if isinstance(value, str):
			candidate = value.strip().lower()
			if candidate in {"main", "main_content", "primary"}:
				return ["main_content"]
			return ["supporting_context"]
		if isinstance(value, list) and len(value) == 0:
			return ["supporting_context"]
		return value

	@field_validator("likely_slide_use")
	@classmethod
	def _validate_unique_likely_slide_use(cls, value: list[str]) -> list[str]:
		if len(value) != len(set(value)):
			raise ValueError("likely_slide_use values must be unique")
		return value


class SectionAnalysisResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_SECTION_ROLE_ALIASES: ClassVar[dict[str, str]] = {
		"framing background": "framing_background",
		"framing_background": "framing_background",
		"background": "framing_background",
		"framing": "framing_background",
		"introduction": "framing_background",
		"intro": "framing_background",
		"administrative": "framing_background",
		"problem definition": "problem_definition",
		"problem_definition": "problem_definition",
		"problem": "problem_definition",
		"motivation": "problem_definition",
		"method explanation": "method_explanation",
		"method_explanation": "method_explanation",
		"method": "method_explanation",
		"methods": "method_explanation",
		"approach": "method_explanation",
		"experiment result interpretation": "experiment_result_interpretation",
		"experiment_result_interpretation": "experiment_result_interpretation",
		"results": "experiment_result_interpretation",
		"result": "experiment_result_interpretation",
		"experiments": "experiment_result_interpretation",
		"experiment": "experiment_result_interpretation",
		"evaluation": "experiment_result_interpretation",
		"limitations discussion": "limitations_discussion",
		"limitations_discussion": "limitations_discussion",
		"limitations": "limitations_discussion",
		"limitation": "limitations_discussion",
		"discussion": "limitations_discussion",
		"caveats": "limitations_discussion",
		"caveat": "limitations_discussion",
		"conclusion takeaways": "conclusion_takeaways",
		"conclusion_takeaways": "conclusion_takeaways",
		"conclusion": "conclusion_takeaways",
		"takeaways": "conclusion_takeaways",
		"takeaway": "conclusion_takeaways",
		"summary": "conclusion_takeaways",
	}

	section_id: str = Field(min_length=1)
	section_title: str
	section_role: list[
		Literal[
			"framing_background",
			"problem_definition",
			"method_explanation",
			"experiment_result_interpretation",
			"limitations_discussion",
			"conclusion_takeaways",
		]
	] = Field(min_length=1)
	summary: str
	key_claims: list[SectionClaim]
	important_details: list[str]
	concepts_needing_explanation: list[ConceptNeedingExplanation]
	evidence_or_arguments: list[EvidenceOrArgument]
	limitations_or_cautions: list[str]
	candidate_visualizable_ideas: list[CandidateVisualizableIdea]
	presentation_relevance: PresentationRelevance
	uncertainty_flags: list[str]
	confidence: Literal["high", "medium", "low"]

	@classmethod
	def _normalize_section_role(cls, value: str) -> str:
		candidate = str(value).strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		mapped = cls._SECTION_ROLE_ALIASES.get(alias_key)
		if mapped:
			return mapped

		tokens = set(alias_key.split())
		if {"administrative", "background", "intro", "introduction", "framing"} & tokens:
			return "framing_background"
		if {"problem", "motivation"} & tokens:
			return "problem_definition"
		if {"method", "methods", "approach"} & tokens:
			return "method_explanation"
		if {"experiment", "experiments", "evaluation", "result", "results"} & tokens:
			return "experiment_result_interpretation"
		if {"limitation", "limitations", "discussion", "caveat", "caveats"} & tokens:
			return "limitations_discussion"
		if {"conclusion", "takeaway", "takeaways", "summary"} & tokens:
			return "conclusion_takeaways"

		return candidate

	@field_validator("section_role", mode="before")
	@classmethod
	def _coerce_section_role_literals(cls, value: Any) -> Any:
		if value is None:
			return ["framing_background"]
		if isinstance(value, str):
			normalized = cls._normalize_section_role(value)
			return [normalized] if normalized else ["framing_background"]
		if not isinstance(value, list):
			return value
		if len(value) == 0:
			return ["framing_background"]
		normalized_values = [cls._normalize_section_role(v) if isinstance(v, str) else v for v in value]
		normalized_values = [item for item in normalized_values if item]
		return normalized_values or ["framing_background"]

	@field_validator("section_role")
	@classmethod
	def _validate_unique_section_role(cls, value: list[str]) -> list[str]:
		if len(value) != len(set(value)):
			raise ValueError("section_role values must be unique")
		return value
