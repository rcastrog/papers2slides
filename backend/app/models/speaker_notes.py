"""Pydantic model for speaker notes outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SlideNote(BaseModel):
	model_config = ConfigDict(extra="forbid")

	slide_number: int = Field(ge=1)
	slide_title: str
	talking_points: list[str] = Field(min_length=1)
	timing_hint_seconds: int = Field(ge=1)
	caution_notes: list[str]


class SpeakerNotes(BaseModel):
	model_config = ConfigDict(extra="forbid")

	deck_language: Literal["en", "es"]
	notes_style: Literal["brief_talking_points"]
	slide_notes: list[SlideNote] = Field(min_length=1)
	global_notes_warnings: list[str]
