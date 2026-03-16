"""Pydantic model for reference retrieval/index output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParsedReference(BaseModel):
	model_config = ConfigDict(extra="forbid")

	title: str
	authors: list[str]
	venue_or_source: str
	year: str
	arxiv_id: str
	doi: str

	@field_validator("title", "venue_or_source", "year", "arxiv_id", "doi", mode="before")
	@classmethod
	def _coerce_nullable_strings(cls, value: Any) -> str:
		if value is None:
			return ""
		return str(value)

	@field_validator("authors", mode="before")
	@classmethod
	def _coerce_authors(cls, value: Any) -> list[str]:
		if value is None:
			return []
		if isinstance(value, list):
			return [str(item) for item in value if item is not None]
		return [str(value)]


class MatchedRecord(BaseModel):
	model_config = ConfigDict(extra="forbid")

	title: str
	authors: list[str]
	year: str
	source: Literal["arxiv", "doi", "web", "other"]
	url: str
	pdf_path: str
	reference_folder_path: str

	@field_validator("title", "year", "url", "pdf_path", "reference_folder_path", mode="before")
	@classmethod
	def _coerce_nullable_strings(cls, value: Any) -> str:
		if value is None:
			return ""
		return str(value)

	@field_validator("authors", mode="before")
	@classmethod
	def _coerce_authors(cls, value: Any) -> list[str]:
		if value is None:
			return []
		if isinstance(value, list):
			return [str(item) for item in value if item is not None]
		return [str(value)]

	@field_validator("source", mode="before")
	@classmethod
	def _coerce_source(cls, value: Any) -> str:
		if value in {"arxiv", "doi", "web", "other"}:
			return str(value)
		return "other"


class AlternativeCandidate(BaseModel):
	model_config = ConfigDict(extra="forbid")

	title: str
	year: str
	reason_not_selected: str


class ReferenceEntry(BaseModel):
	model_config = ConfigDict(extra="forbid")

	reference_id: str = Field(min_length=1)
	original_reference_text: str
	parsed_reference: ParsedReference
	parsing_confidence: Literal["high", "medium", "low"]
	retrieval_status: Literal["retrieved", "ambiguous_match", "not_found", "skipped"]
	matched_record: MatchedRecord
	match_confidence: Literal["high", "medium", "low"]
	alternative_candidates: list[AlternativeCandidate]
	failure_reason: str
	notes: list[str]

	@field_validator("matched_record", mode="before")
	@classmethod
	def _coerce_matched_record(cls, value: Any) -> Any:
		if value is None:
			return {
				"title": "",
				"authors": [],
				"year": "",
				"source": "other",
				"url": "",
				"pdf_path": "",
				"reference_folder_path": "",
			}
		return value

	@field_validator("match_confidence", mode="before")
	@classmethod
	def _coerce_match_confidence(cls, value: Any) -> str:
		if value in {"high", "medium", "low"}:
			return str(value)
		return "low"

	@field_validator("alternative_candidates", mode="before")
	@classmethod
	def _coerce_alternative_candidates(cls, value: Any) -> Any:
		if value is None:
			return []
		return value

	@field_validator("failure_reason", mode="before")
	@classmethod
	def _coerce_failure_reason(cls, value: Any) -> str:
		if value is None:
			return ""
		return str(value)

	@field_validator("notes", mode="before")
	@classmethod
	def _coerce_notes(cls, value: Any) -> list[str]:
		if value is None:
			return []
		if isinstance(value, list):
			return [str(item) for item in value if item is not None]
		return [str(value)]


class RetrievalSummary(BaseModel):
	model_config = ConfigDict(extra="forbid")

	total_references: int = Field(ge=0)
	retrieved_count: int = Field(ge=0)
	ambiguous_count: int = Field(ge=0)
	not_found_count: int = Field(ge=0)
	warnings: list[str]


class ReferenceIndex(BaseModel):
	model_config = ConfigDict(extra="forbid")

	reference_index: list[ReferenceEntry]
	retrieval_summary: RetrievalSummary
