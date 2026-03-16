"""Pydantic model for parsed paper package output."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceStatus(BaseModel):
	model_config = ConfigDict(extra="forbid")

	acquired: bool
	source_type: Literal["pdf_upload", "local_pdf", "url"]
	source_value: str = Field(min_length=1)
	stored_pdf_path: str = Field(min_length=1)
	notes: list[str]


class PaperMetadata(BaseModel):
	model_config = ConfigDict(extra="forbid")

	title: str
	authors: list[str]
	venue_or_source: str
	year: str
	abstract: str
	keywords: list[str]
	metadata_confidence: Literal["high", "medium", "low"]
	inferred_fields: list[str]


class SectionIndexEntry(BaseModel):
	model_config = ConfigDict(extra="forbid")

	section_id: str = Field(min_length=1)
	section_title: str
	section_level: int = Field(ge=1)
	page_start: int = Field(ge=1)
	page_end: int = Field(ge=1)
	order: int = Field(ge=1)
	is_inferred_boundary: bool
	text_path: str = Field(min_length=1)


class BibliographyInfo(BaseModel):
	model_config = ConfigDict(extra="forbid")

	detected: bool
	references_count: int = Field(ge=0)
	references_raw_path: str = Field(min_length=1)
	extraction_confidence: Literal["high", "medium", "low"]


class ParseQuality(BaseModel):
	model_config = ConfigDict(extra="forbid")

	ocr_used: bool
	missing_pages: list[int]
	garbled_regions: list[str]
	suspected_parsing_issues: list[str]
	warnings: list[str]
	overall_confidence: Literal["high", "medium", "low"]

	@field_validator("missing_pages")
	@classmethod
	def _validate_missing_pages(cls, value: list[int]) -> list[int]:
		if any(page < 1 for page in value):
			raise ValueError("missing_pages values must be >= 1")
		return value


class PaperParseResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	source_status: SourceStatus
	metadata: PaperMetadata
	section_index: list[SectionIndexEntry]
	full_text_path: str = Field(min_length=1)
	bibliography: BibliographyInfo
	parse_quality: ParseQuality
