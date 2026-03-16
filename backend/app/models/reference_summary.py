"""Pydantic model for lightweight single-reference summaries."""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReferenceSummaryBody(BaseModel):
	model_config = ConfigDict(extra="forbid")

	main_topic: str
	main_contribution: str
	brief_summary: str


class RelationToSourcePaper(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_RELATION_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"background context": "background_context",
		"background_context": "background_context",
		"method ancestry": "method_ancestry",
		"method_ancestry": "method_ancestry",
		"benchmark dataset context": "benchmark_dataset_context",
		"benchmark_dataset_context": "benchmark_dataset_context",
		"comparison baseline interpretation": "comparison_baseline_interpretation",
		"comparison_baseline_interpretation": "comparison_baseline_interpretation",
		"supporting evidence": "supporting_evidence",
		"supporting_evidence": "supporting_evidence",
		"limitation or contrast": "limitation_or_contrast",
		"limitation_or_contrast": "limitation_or_contrast",
	}

	relation_type: list[
		Literal[
			"background_context",
			"method_ancestry",
			"benchmark_dataset_context",
			"comparison_baseline_interpretation",
			"supporting_evidence",
			"limitation_or_contrast",
		]
	] = Field(min_length=1)
	description: str
	importance_for_source_presentation: Literal["high", "medium", "low"]

	@classmethod
	def _normalize_relation_type(cls, value: str) -> str:
		candidate = str(value).strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		return cls._RELATION_TYPE_ALIASES.get(alias_key, candidate)

	@field_validator("relation_type", mode="before")
	@classmethod
	def _coerce_relation_type_literals(cls, value: Any) -> Any:
		if value is None:
			return ["background_context"]
		if isinstance(value, str):
			return [cls._normalize_relation_type(value)]
		if not isinstance(value, list):
			return value
		if len(value) == 0:
			return ["background_context"]
		return [cls._normalize_relation_type(v) if isinstance(v, str) else v for v in value]

	@field_validator("relation_type")
	@classmethod
	def _validate_unique_relation_type(cls, value: list[str]) -> list[str]:
		if len(value) != len(set(value)):
			raise ValueError("relation_type values must be unique")
		return value


class UsefulPoint(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_USAGE_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"background": "background",
		"background_context": "background",
		"supporting_evidence": "background",
		"supporting evidence": "background",
		"comparison": "comparison",
		"comparison_context": "comparison",
		"method_context": "method_context",
		"method": "method_context",
		"result_context": "result_context",
		"results_context": "result_context",
		"result": "result_context",
		"limitation_context": "limitation_context",
		"limitations_context": "limitation_context",
		"limitation": "limitation_context",
		"other": "other",
	}

	point: str
	usage_type: Literal[
		"background",
		"comparison",
		"method_context",
		"result_context",
		"limitation_context",
		"other",
	]
	support_strength: Literal["strong", "moderate", "weak"]

	@classmethod
	def _normalize_usage_type(cls, value: str) -> str:
		candidate = str(value).strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		return cls._USAGE_TYPE_ALIASES.get(candidate, cls._USAGE_TYPE_ALIASES.get(alias_key, candidate))

	@field_validator("usage_type", mode="before")
	@classmethod
	def _coerce_usage_type_literal(cls, value: Any) -> Any:
		if value is None:
			return "other"
		if not isinstance(value, str):
			return value
		return cls._normalize_usage_type(value)


class PossibleUsefulArtifact(BaseModel):
	model_config = ConfigDict(extra="forbid")

	artifact_hint: str
	artifact_type: Literal["figure", "plot", "chart", "table", "diagram", "equation", "other"]
	why_it_might_help: str

	@field_validator("artifact_type", mode="before")
	@classmethod
	def _coerce_artifact_type(cls, value: Any) -> str:
		if value is None:
			return "other"
		candidate = str(value).strip().lower()
		normalized = re.sub(r"[\s\-/]+", "_", candidate)
		normalized = re.sub(r"_+", "_", normalized).strip("_")

		if normalized in {"figure", "plot", "chart", "table", "diagram", "equation", "other"}:
			return normalized

		# Handle multi-valued outputs like "figure | table" by picking the first known type.
		tokens = re.split(r"[|,;/]+", candidate)
		for token in tokens:
			clean = re.sub(r"[\s\-/]+", "_", token.strip().lower())
			clean = re.sub(r"_+", "_", clean).strip("_")
			if clean in {"figure", "plot", "chart", "table", "diagram", "equation", "other"}:
				return clean

		if "conceptual" in candidate and "figure" in candidate:
			return "figure"
		if "conceptual" in candidate and "diagram" in candidate:
			return "diagram"

		return "other"


class MentionRecommendation(BaseModel):
	model_config = ConfigDict(extra="forbid")

	should_mention_in_final_deck: bool
	recommended_scope: Literal[
		"none",
		"passing_mention",
		"one_bullet_context",
		"one_supporting_slide_note",
	]
	rationale: str


class ReferenceSummary(BaseModel):
	model_config = ConfigDict(extra="forbid")

	reference_id: str = Field(min_length=1)
	reference_title: str
	summary: ReferenceSummaryBody
	relation_to_source_paper: RelationToSourcePaper
	useful_points_for_main_presentation: list[UsefulPoint]
	possible_useful_artifacts: list[PossibleUsefulArtifact]
	mention_recommendation: MentionRecommendation
	warnings: list[str]
	confidence: Literal["high", "medium", "low"]
