"""Pydantic model for generated visual specification outputs."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConceptualBasis(BaseModel):
	model_config = ConfigDict(extra="forbid")

	grounded_in_source_sections: list[str]
	grounded_in_source_artifacts: list[str]
	grounded_in_reference_ids: list[str]


class VisualSpec(BaseModel):
	model_config = ConfigDict(extra="forbid")

	composition: str
	main_elements: list[str]
	labels_or_text: list[str]
	style_notes: list[str]
	language: Literal["en", "es"]


class GeneratedVisualEntry(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_VISUAL_KIND_ALIASES: ClassVar[dict[str, str]] = {
		"process_diagram": "process_diagram",
		"process diagram": "process_diagram",
		"input_output_schematic": "process_diagram",
		"input output schematic": "process_diagram",
		"flowchart": "workflow",
		"flow_chart": "workflow",
		"workflow": "workflow",
		"concept_map": "concept_map",
		"concept map": "concept_map",
		"architecture": "architecture_simplification",
		"architecture_simplification": "architecture_simplification",
		"timeline": "timeline",
		"timeline_summary": "timeline",
		"timeline summary": "timeline",
		"comparison_framework": "comparison_framework",
		"comparison framework": "comparison_framework",
		"demographic_breakdown_chart": "comparison_framework",
		"demographic breakdown chart": "comparison_framework",
		"bar_chart_comparison": "comparison_framework",
		"bar chart comparison": "comparison_framework",
		"mechanism_illustration": "mechanism_illustration",
		"mechanism illustration": "mechanism_illustration",
		"intuitive_abstraction": "other",
		"intuitive abstraction": "other",
		"other": "other",
	}

	_ALLOWED_VISUAL_KINDS: ClassVar[set[str]] = {
		"process_diagram",
		"concept_map",
		"workflow",
		"architecture_simplification",
		"timeline",
		"comparison_framework",
		"mechanism_illustration",
		"other",
	}

	visual_id: str = Field(min_length=1)
	slide_number: int = Field(ge=1)
	slide_title: str
	visual_purpose: str
	visual_kind: Literal[
		"process_diagram",
		"concept_map",
		"workflow",
		"architecture_simplification",
		"timeline",
		"comparison_framework",
		"mechanism_illustration",
		"other",
	]
	status: Literal["recommended", "optional", "not_needed"]
	conceptual_basis: ConceptualBasis
	provenance_label: Literal["conceptual", "adapted_from_source"]
	must_preserve_if_adapted: list[str]
	visual_spec: VisualSpec
	safety_notes: list[str]
	image_generation_prompt: str

	@field_validator("visual_kind", mode="before")
	@classmethod
	def _coerce_visual_kind(cls, value: Any) -> str:
		if value is None:
			return "other"
		candidate = str(value).strip().lower()
		candidate = candidate.replace("-", " ").replace("_", " ")
		candidate = " ".join(candidate.split())

		canonical = cls._VISUAL_KIND_ALIASES.get(candidate)
		if canonical:
			return canonical

		compact = candidate.replace(" ", "_")
		if compact in cls._ALLOWED_VISUAL_KINDS:
			return compact

		return "other"


class GeneratedVisuals(BaseModel):
	model_config = ConfigDict(extra="forbid")

	generated_visuals: list[GeneratedVisualEntry]
	global_visual_warnings: list[str]
