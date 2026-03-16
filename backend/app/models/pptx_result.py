"""Pydantic model for PPTX renderer outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PPTXOutput(BaseModel):
	model_config = ConfigDict(extra="forbid")

	pptx_path: str
	template_used: str
	notes_insertion_supported: bool


class PPTXAssetUsage(BaseModel):
	model_config = ConfigDict(extra="forbid")

	asset_id: str
	resolved_path: str


class SlideBuildResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	slide_number: int = Field(ge=1)
	title: str
	status: Literal["built", "built_with_warning", "failed"]
	assets_used: list[PPTXAssetUsage]
	notes_inserted: bool
	citations_inserted: bool
	warnings: list[str]


class PPTXDeviation(BaseModel):
	model_config = ConfigDict(extra="forbid")

	type: Literal["missing_asset", "pptx_layout_approximation", "note_insertion_issue", "citation_issue", "other"]
	description: str


class PPTXBuildResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	build_status: Literal["success", "partial_success", "failed"]
	output: PPTXOutput
	slide_build_results: list[SlideBuildResult]
	global_warnings: list[str]
	deviations: list[PPTXDeviation]
