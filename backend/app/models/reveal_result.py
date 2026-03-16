"""Pydantic model for Reveal renderer outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RevealOutput(BaseModel):
	model_config = ConfigDict(extra="forbid")

	reveal_root_path: str
	entry_html_path: str
	assets_directory: str
	theme_name: str


class RevealAssetUsage(BaseModel):
	model_config = ConfigDict(extra="forbid")

	asset_id: str
	resolved_path: str
	source_origin: Literal["source_paper", "reference_paper", "generated"]


class SlideRenderResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	slide_number: int = Field(ge=1)
	title: str
	status: Literal["rendered", "rendered_with_warning", "failed"]
	assets_used: list[RevealAssetUsage]
	citations_rendered: list[str]
	notes_attached: bool
	warnings: list[str]


class RevealDeviation(BaseModel):
	model_config = ConfigDict(extra="forbid")

	type: Literal["missing_asset", "layout_constraint", "citation_truncation", "note_attachment_issue", "other"]
	description: str


class RevealRenderResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	render_status: Literal["success", "partial_success", "failed"]
	output: RevealOutput
	slide_render_results: list[SlideRenderResult]
	global_warnings: list[str]
	deviations: list[RevealDeviation]
