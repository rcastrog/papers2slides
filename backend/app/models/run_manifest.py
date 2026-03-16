"""Pydantic model for orchestration run manifest state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StageExecution(BaseModel):
    """Per-stage execution status and timing metadata."""

    model_config = ConfigDict(extra="allow")

    stage: str
    status: Literal["running", "completed", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None


class RunManifest(BaseModel):
    """Runtime manifest persisted in logs/run_manifest.json."""

    model_config = ConfigDict(extra="allow")

    run_id: str = Field(min_length=1)
    status: Literal[
        "queued",
        "running",
        "checkpoint_waiting",
        "completed",
        "completed_with_warnings",
        "failed",
    ]
    current_stage: str
    llm_mode: str | None = None
    llm_mode_reason: str | None = None
    completed_stages: list[str] = Field(default_factory=list)
    stages: list[StageExecution] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    checkpoint_state: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    run_summary: dict[str, Any] = Field(default_factory=dict)
