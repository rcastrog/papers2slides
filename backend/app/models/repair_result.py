"""Pydantic model for narrow targeted repair agent outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RepairResult(BaseModel):
    """Generic repair response contract for slide/citation/visual/notes/translation repairs."""

    model_config = ConfigDict(extra="forbid")

    repair_status: Literal["applied", "no_change", "failed"]
    target_ids: list[str]
    changes_made: list[str]
    unresolved_risks: list[str]
    repair_confidence: Literal["high", "medium", "low"]
    warnings: list[str]
