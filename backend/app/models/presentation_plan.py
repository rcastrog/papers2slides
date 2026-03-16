"""Pydantic model for presentation planning output."""

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeckMetadata(BaseModel):
	model_config = ConfigDict(extra="forbid")

	title: str
	subtitle: str
	language: Literal["en", "es"]
	presentation_style: Literal[
		"journal_club",
		"teaching",
		"executive_friendly",
		"technical_summary",
	]
	target_audience: Literal[
		"research_specialists",
		"technical_adjacent",
		"students",
		"executive_nontechnical",
	]
	target_duration_minutes: int = Field(ge=1)
	target_slide_count: int = Field(ge=1)


class NarrativeArc(BaseModel):
	model_config = ConfigDict(extra="forbid")

	overall_story: str
	audience_adaptation_notes: list[str]
	language_adaptation_notes: list[str]


class SlideVisual(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_VISUAL_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"source_figure": "source_figure",
		"source_image": "source_figure",
		"figure": "source_figure",
		"source_table": "source_table",
		"table": "source_table",
		"source_chart": "source_chart",
		"source_plot": "source_chart",
		"plot": "source_chart",
		"chart": "source_chart",
		"graph": "source_chart",
		"source_graph": "source_chart",
		"source_diagram": "source_diagram",
		"diagram": "source_diagram",
		"generated_conceptual": "generated_conceptual",
		"conceptual": "generated_conceptual",
		"generated": "generated_conceptual",
		"text_only": "text_only",
		"text": "text_only",
		"none": "text_only",
		"other": "other",
	}

	_USAGE_MODE_ALIASES: ClassVar[dict[str, str]] = {
		"reuse": "reuse",
		"adapted": "adapted",
		"conceptual": "conceptual",
		"none": "none",
		"reuse_directly": "reuse",
		"crop_or_clean": "adapted",
		"recreate_carefully": "adapted",
		"replace_with_conceptual_visual": "conceptual",
		"avoid_using": "none",
	}

	visual_type: Literal[
		"source_figure",
		"source_table",
		"source_chart",
		"source_diagram",
		"generated_conceptual",
		"text_only",
		"other",
	]
	asset_id: str
	source_origin: Literal["source_paper", "reference_paper", "generated", "none"]
	usage_mode: Literal["reuse", "adapted", "conceptual", "none"]
	placement_hint: Literal[
		"full_bleed",
		"left_visual_right_text",
		"right_visual_left_text",
		"two_column",
		"center_focus",
		"other",
	]
	why_this_visual: str

	@field_validator("visual_type", mode="before")
	@classmethod
	def _coerce_visual_type(cls, value: Any) -> Any:
		if value is None:
			return "other"
		if not isinstance(value, str):
			return value
		candidate = value.strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		return cls._VISUAL_TYPE_ALIASES.get(candidate, cls._VISUAL_TYPE_ALIASES.get(alias_key, candidate))

	@field_validator("asset_id", mode="before")
	@classmethod
	def _coerce_asset_id(cls, value: Any) -> str:
		if value is None:
			return "none"
		return str(value)

	@field_validator("usage_mode", mode="before")
	@classmethod
	def _coerce_usage_mode(cls, value: Any) -> str:
		if value is None:
			return "none"
		candidate = str(value).strip().lower()
		return cls._USAGE_MODE_ALIASES.get(candidate, candidate)


class SourceSupport(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_SUPPORT_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"source_section": "source_section",
		"source_metadata": "source_section",
		"section": "source_section",
		"source_artifact": "source_artifact",
		"artifact": "source_artifact",
		"reference_summary": "reference_summary",
		"reference": "reference_summary",
	}

	support_type: Literal["source_section", "source_artifact", "reference_summary"]
	support_id: str
	support_note: str

	@field_validator("support_type", mode="before")
	@classmethod
	def _coerce_support_type(cls, value: Any) -> str:
		if value is None:
			return "source_section"
		candidate = str(value).strip().lower()
		return cls._SUPPORT_TYPE_ALIASES.get(candidate, candidate)


class SlideCitation(BaseModel):
	model_config = ConfigDict(extra="forbid")

	short_citation: str
	source_kind: Literal["source_paper", "reference_paper"]
	citation_purpose: Literal[
		"source_of_claim",
		"method_background",
		"contextual_reference",
		"attribution",
	] = "contextual_reference"


class PlannedSlide(BaseModel):
	model_config = ConfigDict(extra="forbid")

	slide_number: int = Field(ge=1)
	slide_role: Literal[
		"title",
		"motivation",
		"problem",
		"contribution",
		"method",
		"result",
		"discussion",
		"limitation",
		"conclusion",
		"appendix_like_support",
	]
	title: str
	objective: str
	key_points: list[str]
	must_avoid: list[str]
	visuals: list[SlideVisual]
	source_support: list[SourceSupport]
	citations: list[SlideCitation]
	speaker_note_hooks: list[str]
	confidence_notes: list[str]
	layout_hint: str


class PresentationPlan(BaseModel):
	model_config = ConfigDict(extra="forbid")

	deck_metadata: DeckMetadata
	narrative_arc: NarrativeArc
	slides: list[PlannedSlide] = Field(min_length=1)
	global_warnings: list[str]
	plan_confidence: Literal["high", "medium", "low"]
