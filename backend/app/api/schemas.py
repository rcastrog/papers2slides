"""API request and response schemas for thin job/run endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobSubmissionRequest(BaseModel):
    """Minimal job submission payload for JSON requests."""

    source_url: str | None = None
    presentation_style: str = "journal_club"
    audience: str = "research_specialists"
    language: str = "en"
    output_formats: list[str] = Field(default_factory=lambda: ["reveal", "pptx"])
    repair_on_audit: bool = False
    advanced_options: dict[str, Any] | None = None


class JobSubmissionResponse(BaseModel):
    """Response returned when a job is accepted."""

    run_id: str
    status: str
    status_url: str
    results_url: str


class RunStatusResponse(BaseModel):
    """Run status payload served to polling clients."""

    run_id: str
    status: str
    current_stage: str
    completed_stages: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    warning_count: int = 0
    key_artifact_paths: dict[str, str] = Field(default_factory=dict)
    checkpoint_state: dict[str, Any] = Field(default_factory=dict)
    audit_findings_count: int | None = None
    stage_count: int = 0
    fallback_stage_count: int = 0
    total_duration_ms: int | None = None
    job_summary: dict[str, Any] = Field(default_factory=dict)


class RunResultsResponse(BaseModel):
    """Structured run outputs summary for results page."""

    run_id: str
    reveal_path: str | None = None
    pptx_path: str | None = None
    notes_path: str | None = None
    audit_report_path: str | None = None
    final_risk_summary: dict[str, Any] = Field(default_factory=dict)
    asset_usage_summary: dict[str, Any] = Field(default_factory=dict)


class StageInspectionResponse(BaseModel):
    """Per-stage execution details for run inspector UI."""

    stage: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None


class RunInspectionResponse(BaseModel):
    """Full run-level inspection payload for human review."""

    run_id: str
    status: str
    current_stage: str
    llm_mode: str | None = None
    llm_mode_reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    warning_count: int = 0
    error_count: int = 0
    completed_stages: list[str] = Field(default_factory=list)
    stages: list[StageInspectionResponse] = Field(default_factory=list)
    quality_signals: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    extracted_assets_summary: dict[str, Any] = Field(default_factory=dict)
    asset_map_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
