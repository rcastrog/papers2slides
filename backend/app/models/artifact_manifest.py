"""Pydantic model for extracted artifact manifests."""

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ArtifactEntry(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_ARTIFACT_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"figure": "figure",
		"conceptual figure": "figure",
		"conceptual_figure": "figure",
		"plot": "plot",
		"chart": "chart",
		"table": "table",
		"diagram": "diagram",
		"conceptual diagram": "diagram",
		"conceptual_diagram": "diagram",
		"equation": "equation",
		"formula": "equation",
		"composite": "composite",
		"mixed": "composite",
		"other": "other",
	}

	artifact_id: str = Field(min_length=1)
	artifact_label: str
	artifact_type: Literal[
		"figure",
		"plot",
		"chart",
		"table",
		"diagram",
		"equation",
		"composite",
		"other",
	]
	page_numbers: list[int] = Field(min_length=1)
	section_id: str
	caption: str
	nearby_context_summary: str
	file_path: str
	extraction_quality: Literal["high", "medium", "low"]
	readability_for_presentation: Literal["high", "medium", "low"]
	core_message: str
	presentation_value: Literal["high", "medium", "low"]
	recommended_action: Literal[
		"reuse_directly",
		"crop_or_clean",
		"recreate_carefully",
		"replace_with_conceptual_visual",
		"avoid_using",
	]
	recommendation_rationale: str
	must_preserve_if_adapted: list[str]
	distortion_risk: Literal["high", "medium", "low"]
	ambiguities: list[str]
	notes: list[str]

	@field_validator("artifact_type", mode="before")
	@classmethod
	def _coerce_artifact_type(cls, value: Any) -> str:
		if value is None:
			return "other"
		candidate = str(value).strip().lower()
		candidate = re.sub(r"[\s\-/]+", "_", candidate)
		candidate = re.sub(r"_+", "_", candidate).strip("_")
		alias_key = candidate.replace("_", " ")
		return cls._ARTIFACT_TYPE_ALIASES.get(alias_key, candidate)

	@field_validator("page_numbers")
	@classmethod
	def _validate_page_numbers(cls, value: list[int]) -> list[int]:
		if any(page < 1 for page in value):
			raise ValueError("page_numbers values must be >= 1")
		if len(value) != len(set(value)):
			raise ValueError("page_numbers values must be unique")
		return value


class ArtifactSummary(BaseModel):
	model_config = ConfigDict(extra="forbid")

	artifact_count: int = Field(ge=0)
	high_value_artifact_ids: list[str]
	high_risk_artifact_ids: list[str]
	equation_artifact_ids: list[str]
	warnings: list[str]


class ArtifactManifest(BaseModel):
	model_config = ConfigDict(extra="forbid")

	artifacts: list[ArtifactEntry]
	summary: ArtifactSummary

	@model_validator(mode="before")
	@classmethod
	def _coerce_manifest_shape(cls, value: Any) -> Any:
		if not isinstance(value, dict):
			return value

		normalized = dict(value)
		warnings: list[str] = []

		artifacts_value = normalized.get("artifacts")
		if artifacts_value is None:
			warnings.append("A3 output missing artifacts list; normalized to empty manifest.")
			normalized["artifacts"] = []
		elif isinstance(artifacts_value, dict):
			normalized["artifacts"] = [artifacts_value]
		elif not isinstance(artifacts_value, list):
			warnings.append("A3 artifacts field had invalid shape; normalized to empty list.")
			normalized["artifacts"] = []

		summary_value = normalized.get("summary")
		if not isinstance(summary_value, dict):
			if summary_value not in (None, ""):
				warnings.append("A3 summary field had invalid shape; synthesized fallback summary.")
			normalized["summary"] = {
				"artifact_count": len(normalized.get("artifacts", [])),
				"high_value_artifact_ids": [],
				"high_risk_artifact_ids": [],
				"equation_artifact_ids": [],
				"warnings": warnings,
			}
		else:
			summary = dict(summary_value)
			for list_key in ["high_value_artifact_ids", "high_risk_artifact_ids", "equation_artifact_ids", "warnings"]:
				if list_key not in summary or not isinstance(summary.get(list_key), list):
					summary[list_key] = []
			if "artifact_count" not in summary or not isinstance(summary.get("artifact_count"), int):
				summary["artifact_count"] = len(normalized.get("artifacts", []))
			if warnings:
				summary["warnings"].extend(warnings)
			normalized["summary"] = summary

		return {
			"artifacts": normalized.get("artifacts", []),
			"summary": normalized.get("summary", {
				"artifact_count": 0,
				"high_value_artifact_ids": [],
				"high_risk_artifact_ids": [],
				"equation_artifact_ids": [],
				"warnings": warnings,
			}),
		}
