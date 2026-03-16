"""Pydantic model for job specification payloads."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobSource(BaseModel):
	model_config = ConfigDict(extra="forbid")

	source_type: Literal["pdf_upload", "local_pdf", "url"]
	source_value: str = Field(min_length=1)


class JobSpec(BaseModel):
	model_config = ConfigDict(extra="forbid")

	job_id: str = Field(min_length=1)
	source: JobSource
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
	language: Literal["en", "es"]
	output_formats: list[Literal["reveal", "pptx"]] = Field(min_length=1)
	target_duration_minutes: int = Field(ge=1)
	target_slide_count: int = Field(ge=1)
	automation_mode: Literal["end_to_end", "checkpointed"]
	approval_checkpoints_enabled: bool
	checkpoints: list[
		Literal[
			"parse_summary",
			"presentation_plan",
			"render_review",
			"audit_review",
		]
	]
	reference_mode: Literal["retrieve_all_light_summarize"]
	visual_policy: Literal["conservative", "balanced", "enhanced"]
	equation_policy: Literal["avoid_unless_essential", "include_when_central"]
	citation_style: str = Field(min_length=1)
	speaker_notes_style: Literal["brief_talking_points"]
	user_notes: list[str]
	defaults_applied: list[str]
	warnings: list[str]
	validation_errors: list[str]

	@field_validator("output_formats", "checkpoints")
	@classmethod
	def _require_unique_values(cls, value: list[str]) -> list[str]:
		if len(value) != len(set(value)):
			raise ValueError("List items must be unique")
		return value
