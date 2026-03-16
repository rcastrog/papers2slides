"""Pydantic model for auditor outputs and repair prioritization."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceBasisItem(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_SOURCE_TYPE_ALIASES: ClassVar[dict[str, str]] = {
		"source_section": "source_section",
		"source_artifact": "source_artifact",
		"reference_summary": "reference_summary",
		"reference_summaries": "reference_summary",
		"reference summaries": "reference_summary",
		"presentation_plan": "presentation_plan",
		"speaker_notes": "speaker_notes",
		"render_output": "render_output",
		"generated_visual": "render_output",
		"generated_visuals": "render_output",
	}

	source_type: Literal[
		"source_section",
		"source_artifact",
		"reference_summary",
		"presentation_plan",
		"speaker_notes",
		"render_output",
	]
	source_id: str
	note: str

	@field_validator("source_type", mode="before")
	@classmethod
	def _coerce_source_type(cls, value: Any) -> str:
		if value is None:
			return "render_output"
		candidate = str(value).strip().lower()
		return cls._SOURCE_TYPE_ALIASES.get(candidate, candidate)


class SlideFinding(BaseModel):
	model_config = ConfigDict(extra="forbid")

	severity: Literal["low", "medium", "high"]
	category: Literal[
		"unsupported_claim",
		"overclaim",
		"artifact_distortion_risk",
		"generated_visual_overreach",
		"citation_issue",
		"translation_drift",
		"notes_issue",
		"omitted_limitation",
		"provenance_issue",
		"other",
	]
	description: str
	evidence_basis: list[EvidenceBasisItem]
	recommended_fix: str


class SlideAudit(BaseModel):
	model_config = ConfigDict(extra="forbid")

	slide_number: int = Field(ge=1)
	slide_title: str
	overall_support: Literal["supported", "weakly_supported", "unsupported"]
	findings: list[SlideFinding]
	required_action: Literal[
		"none",
		"revise_slide",
		"revise_notes",
		"revise_visual",
		"remove_claim",
		"add_citation",
		"add_caveat",
	]


class DeckLevelFinding(BaseModel):
	model_config = ConfigDict(extra="forbid")

	_CATEGORY_ALIASES: ClassVar[dict[str, str]] = {
		"systemic_overclaiming": "systemic_overclaiming",
		"unsupported_claim": "systemic_overclaiming",
		"overclaim": "systemic_overclaiming",
		"insufficient_limitations": "insufficient_limitations",
		"omitted_limitation": "insufficient_limitations",
		"weak_reference_use": "weak_reference_use",
		"citation_issue": "weak_reference_use",
		"translation_quality": "translation_quality",
		"translation_drift": "translation_quality",
		"provenance_consistency": "provenance_consistency",
		"artifact_fidelity": "provenance_consistency",
		"generated_visual_overreach": "provenance_consistency",
		"artifact_distortion_risk": "provenance_consistency",
		"provenance_issue": "provenance_consistency",
		"notes_issue": "other",
		"other": "other",
	}

	severity: Literal["low", "medium", "high"]
	category: Literal[
		"systemic_overclaiming",
		"insufficient_limitations",
		"weak_reference_use",
		"translation_quality",
		"provenance_consistency",
		"other",
	]
	description: str
	recommended_fix: str

	@field_validator("category", mode="before")
	@classmethod
	def _coerce_category(cls, value: Any) -> str:
		if value is None:
			return "other"
		candidate = str(value).strip().lower()
		return cls._CATEGORY_ALIASES.get(candidate, candidate)


class RepairPriorityItem(BaseModel):
	model_config = ConfigDict(extra="forbid")

	priority_order: int = Field(ge=1)
	slide_number: int = Field(ge=0)
	reason: str


class AuditReport(BaseModel):
	model_config = ConfigDict(extra="forbid")

	audit_status: Literal["completed", "completed_with_warnings", "failed"]
	deck_risk_level: Literal["low", "medium", "high"]
	slide_audits: list[SlideAudit]
	deck_level_findings: list[DeckLevelFinding]
	repair_priority: list[RepairPriorityItem]
	global_warnings: list[str]

	@field_validator("global_warnings", mode="before")
	@classmethod
	def _coerce_global_warnings(cls, value: Any) -> list[str]:
		if value is None:
			return []

		if isinstance(value, list):
			warnings: list[str] = []
			for item in value:
				if isinstance(item, str):
					candidate = item.strip()
					if candidate:
						warnings.append(candidate)
					continue

				if isinstance(item, dict):
					description = str(item.get("description", "")).strip()
					severity = str(item.get("severity", "")).strip().lower()
					if description and severity in {"low", "medium", "high"}:
						warnings.append(f"[{severity}] {description}")
					elif description:
						warnings.append(description)
					else:
						warnings.append(str(item))
					continue

				candidate = str(item).strip()
				if candidate:
					warnings.append(candidate)

			return warnings

		candidate = str(value).strip()
		return [candidate] if candidate else []
