"""Run status and results route handlers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse

from app.api.routes.jobs import _execute_workflow
from app.api.schemas import JobSubmissionResponse, RunResultsResponse, RunStatusResponse
from app.orchestrator.workflow import compute_repetition_metrics_from_payload, recover_a11_only
from app.services.run_inspector import RunInspector
from app.storage.run_manager import RunManager

router = APIRouter(tags=["runs"])
_STALLED_RUNNING_SECONDS = 300


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    """Return current run status from run manifest (source of truth)."""
    run_path = _resolve_run_path(run_id)

    manifest_path = run_path / "logs" / "run_manifest.json"
    manifest = _load_json(manifest_path)
    if manifest is None:
        workflow_summary = _load_json(run_path / "logs" / "workflow_summary.json")
        if workflow_summary is None:
            raise HTTPException(status_code=404, detail="Run status not available")

        manifest = {
            "run_id": run_id,
            "status": "completed",
            "current_stage": "A11",
            "completed_stages": workflow_summary.get("completed_stages", []),
            "warnings": [],
            "artifacts": workflow_summary.get("final_output_paths_after_repair", {}),
            "checkpoint_state": {},
        }
    else:
        stale_seconds = _manifest_age_seconds(manifest_path)
        normalized_manifest, updated = _finalize_stalled_manifest_if_needed(
            manifest,
            stale_seconds=stale_seconds,
        )
        if updated:
            run_manager = _resolve_run_manager(run_path)
            run_manager.save_json("logs/run_manifest.json", normalized_manifest)
        manifest = normalized_manifest

    audit_findings_count = _count_audit_findings(run_path)
    warnings = manifest.get("warnings", [])
    stage_entries = manifest.get("stages", [])
    if not isinstance(stage_entries, list):
        stage_entries = []
    stage_warnings = [
        {
            "stage": str(stage.get("stage") or "unknown"),
            "warnings": [str(item) for item in (stage.get("warnings") or []) if str(item).strip()],
        }
        for stage in stage_entries
        if isinstance(stage, dict) and isinstance(stage.get("warnings"), list) and stage.get("warnings")
    ]
    global_warnings = [str(item) for item in warnings if str(item).strip()]
    stage_warning_text = {
        item
        for group in stage_warnings
        for item in group.get("warnings", [])
        if isinstance(item, str) and item.strip()
    }
    global_warnings = [item for item in global_warnings if item not in stage_warning_text]
    if global_warnings:
        stage_warnings.insert(0, {"stage": "run_global", "warnings": global_warnings})
    fallback_stage_count = sum(1 for stage in stage_entries if isinstance(stage, dict) and stage.get("fallback_used"))

    return RunStatusResponse(
        run_id=manifest.get("run_id", run_id),
        source_pdf_name=_resolve_source_pdf_name(run_path),
        status=manifest.get("status", "running"),
        current_stage=manifest.get("current_stage", "unknown"),
        completed_stages=manifest.get("completed_stages", []),
        warnings=warnings,
        stage_warnings=stage_warnings,
        warning_count=len(warnings),
        key_artifact_paths=manifest.get("artifacts", {}),
        checkpoint_state=manifest.get("checkpoint_state", {}),
        audit_findings_count=audit_findings_count,
        stage_count=len(stage_entries),
        fallback_stage_count=fallback_stage_count,
        total_duration_ms=manifest.get("duration_ms"),
        job_summary=(manifest.get("run_summary", {}) or {}).get("job_summary", {}),
    )


def _resolve_source_pdf_name(run_path: Path) -> str | None:
    candidates = [
        run_path / "source_paper",
        run_path / "input",
    ]
    for folder in candidates:
        if not folder.is_dir():
            continue
        pdfs = sorted(folder.glob("*.pdf"))
        if pdfs:
            return pdfs[0].name
    return None


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, object]:
    """Request cooperative cancellation for a queued/running run."""
    run_path = _resolve_run_path(run_id)
    run_manager = _resolve_run_manager(run_path)

    manifest = _load_json(run_path / "logs" / "run_manifest.json")
    if manifest is None:
        raise HTTPException(status_code=404, detail="Run manifest not found")

    status = str(manifest.get("status", "")).strip().lower()
    if status in {"completed", "completed_with_warnings", "failed", "cancelled"}:
        return {
            "run_id": run_id,
            "status": manifest.get("status", "unknown"),
            "message": "Run is already terminal and cannot be cancelled.",
        }

    checkpoint_state = manifest.get("checkpoint_state")
    if not isinstance(checkpoint_state, dict):
        checkpoint_state = {}
    checkpoint_state["cancel_requested"] = True
    checkpoint_state["cancel_requested_at"] = datetime.now(UTC).isoformat()

    manifest["status"] = "cancel_requested"
    manifest["checkpoint_state"] = checkpoint_state

    run_manager.save_json("logs/run_manifest.json", manifest)
    return {
        "run_id": run_id,
        "status": "cancel_requested",
        "message": "Cancellation requested. The workflow will stop at the next stage boundary.",
    }


@router.post("/runs/{run_id}/recover-a11")
def recover_run_a11(run_id: str) -> dict[str, object]:
    """Recover a failed run by re-executing only A11 from existing artifacts."""
    run_path = _resolve_run_path(run_id)
    try:
        recovery = recover_a11_only(run_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"A11 recovery failed: {exc}") from exc

    return {
        "run_id": run_id,
        "status": recovery.get("status", "completed"),
        "audit_report_path": recovery.get("audit_report_path"),
        "deck_risk_level": recovery.get("deck_risk_level"),
        "unresolved_high_severity_findings_count": recovery.get("unresolved_high_severity_findings_count"),
    }


@router.post("/runs/{run_id}/retry", response_model=JobSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
def retry_run(run_id: str, background_tasks: BackgroundTasks) -> JobSubmissionResponse:
    """Create a new run by reusing a failed run's input PDF and workflow options."""
    source_run_path = _resolve_run_path(run_id)
    source_manifest = _load_json(source_run_path / "logs" / "run_manifest.json")
    if source_manifest is None:
        raise HTTPException(status_code=404, detail="Run manifest not found")

    source_status = str(source_manifest.get("status", "")).strip().lower()
    if source_status != "failed":
        raise HTTPException(status_code=400, detail="Only failed runs can be retried")

    source_pdf_path = _find_source_pdf_for_retry(source_run_path)
    workflow_options, repair_on_audit = _build_retry_configuration(source_run_path, source_manifest)

    backend_root = Path(__file__).resolve().parents[3]
    runs_root = backend_root / "runs"
    run_manager = RunManager(runs_root)

    new_run_path = run_manager.create_run(slug="api-job")
    new_run_id = new_run_path.name

    input_dir = new_run_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    new_pdf_path = input_dir / source_pdf_path.name
    shutil.copy2(source_pdf_path, new_pdf_path)

    queued_manifest = {
        "run_id": new_run_id,
        "status": "queued",
        "current_stage": "A0",
        "completed_stages": [],
        "stages": [],
        "warnings": [],
        "errors": [],
        "artifacts": {},
        "checkpoint_state": {},
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "run_summary": {
            "retry_of": run_id,
        },
    }
    run_manager.save_json("logs/run_manifest.json", queued_manifest)

    background_tasks.add_task(
        _execute_workflow,
        new_pdf_path,
        new_run_path,
        repair_on_audit,
        workflow_options,
    )

    return JobSubmissionResponse(
        run_id=new_run_id,
        status="queued",
        status_url=f"/runs/{new_run_id}",
        results_url=f"/runs/{new_run_id}/results",
    )


@router.get("/runs/{run_id}/results", response_model=RunResultsResponse)
def get_run_results(run_id: str) -> RunResultsResponse:
    """Return structured output summary for a completed run."""
    run_path = _resolve_run_path(run_id)

    results = _load_json(run_path / "logs" / "results_summary.json")
    workflow_summary = _load_json(run_path / "logs" / "workflow_summary.json")
    if results is None and workflow_summary is None:
        raise HTTPException(status_code=404, detail="Run results are not available")

    results = _build_results_payload(
        run_id=run_id,
        run_path=run_path,
        results=results,
        workflow_summary=workflow_summary,
    )

    if not isinstance(results.get("asset_usage_summary"), dict) or not results.get("asset_usage_summary"):
        inspector = RunInspector(run_path)
        extracted_assets = inspector.get_extracted_assets()
        asset_map = inspector.get_asset_map()
        visual_resolution = asset_map.get("visual_resolution", []) if isinstance(asset_map.get("visual_resolution", []), list) else []

        slides_using_real = {
            int(item.get("slide_number", 0) or 0)
            for item in visual_resolution
            if isinstance(item, dict)
            and item.get("source_origin") == "source_paper"
            and not bool(item.get("fallback_used", True))
        }

        results["asset_usage_summary"] = {
            "extracted_assets_count": extracted_assets.get("count", 0),
            "asset_map_resolved": asset_map.get("resolved_count", 0),
            "asset_map_total": asset_map.get("entry_count", 0),
            "slides_using_real_source_figures": len(slides_using_real),
        }

    return RunResultsResponse.model_validate(results)


def _build_results_payload(
    *,
    run_id: str,
    run_path: Path,
    results: dict[str, Any] | None,
    workflow_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a complete results payload, filling missing fields from workflow artifacts."""
    payload = dict(results or {})
    summary = dict(workflow_summary or {})
    final_paths = summary.get("final_output_paths_after_repair", {})
    if not isinstance(final_paths, dict):
        final_paths = {}

    payload["run_id"] = str(payload.get("run_id") or run_id)

    if not payload.get("reveal_path"):
        payload["reveal_path"] = final_paths.get("reveal_entry_html")
    if not payload.get("pptx_path"):
        payload["pptx_path"] = final_paths.get("pptx_path")

    if not payload.get("reveal_path"):
        reveal_candidate = run_path / "presentation" / "reveal" / "index.html"
        if reveal_candidate.is_file():
            payload["reveal_path"] = str(reveal_candidate)

    if not payload.get("pptx_path"):
        pptx_candidates = [
            run_path / "presentation" / "pptx" / "deck.pptx",
            run_path / "presentation" / "pptx_repaired" / "deck.pptx",
            run_path / "output" / "presentation.pptx",
        ]
        for candidate in pptx_candidates:
            if candidate.is_file():
                payload["pptx_path"] = str(candidate)
                break

    if not payload.get("notes_path"):
        notes_path = run_path / "presentation" / "speaker_notes.json"
        payload["notes_path"] = str(notes_path) if notes_path.is_file() else None

    if not payload.get("audit_report_path"):
        payload["audit_report_path"] = summary.get("audit_report_path")

    final_risk = payload.get("final_risk_summary")
    if not isinstance(final_risk, dict):
        final_risk = {}
    if "deck_risk_level" not in final_risk:
        final_risk["deck_risk_level"] = summary.get("deck_risk_level_final")
    if "unresolved_high_severity_findings_count" not in final_risk:
        final_risk["unresolved_high_severity_findings_count"] = summary.get("unresolved_high_severity_findings_count", 0)
    payload["final_risk_summary"] = final_risk

    asset_usage = payload.get("asset_usage_summary")
    if not isinstance(asset_usage, dict):
        payload["asset_usage_summary"] = {}

    repetition_metrics = payload.get("repetition_metrics")
    if not isinstance(repetition_metrics, dict) or not repetition_metrics:
        repetition_metrics = _load_repetition_metrics_for_run(run_path)
    payload["repetition_metrics"] = repetition_metrics if isinstance(repetition_metrics, dict) else {}

    return payload


def _load_repetition_metrics_for_run(run_path: Path) -> dict[str, Any]:
    candidates = [
        run_path / "presentation" / "presentation_plan_repaired.json",
        run_path / "presentation" / "presentation_plan.json",
    ]
    for candidate in candidates:
        payload = _load_json(candidate)
        if isinstance(payload, dict):
            metrics = compute_repetition_metrics_from_payload(payload)
            if metrics:
                return metrics
    return {}


@router.get("/runs/{run_id}/download/{artifact_name}")
def download_artifact(run_id: str, artifact_name: str) -> FileResponse:
    """Stream a known artifact file when it exists."""
    run_path = _resolve_run_path(run_id)
    results = get_run_results(run_id)

    artifact_map = {
        "reveal": results.reveal_path,
        "pptx": results.pptx_path,
        "notes": results.notes_path,
        "audit": results.audit_report_path,
    }

    selected = artifact_map.get(artifact_name)
    if not selected:
        raise HTTPException(status_code=404, detail="Unknown artifact name")

    candidate = Path(selected)
    if not candidate.is_absolute():
        candidate = (run_path / candidate).resolve()

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return FileResponse(path=candidate, filename=candidate.name)


@router.get("/runs/{run_id}/reveal/index.html")
def get_reveal_index(run_id: str) -> FileResponse:
    """Serve the reveal entry HTML from within the run folder."""
    run_path = _resolve_run_path(run_id)
    results = get_run_results(run_id)

    selected = results.reveal_path
    candidate = _resolve_reveal_index_path(run_path=run_path, selected_path=selected)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Reveal output not found")

    return FileResponse(path=candidate, media_type="text/html")


@router.get("/runs/{run_id}/reveal/assets/{asset_path:path}")
def get_reveal_asset(run_id: str, asset_path: str) -> FileResponse:
    """Serve reveal assets while preventing path traversal."""
    run_path = _resolve_run_path(run_id)
    candidate = _resolve_reveal_asset_path(run_path=run_path, asset_path=asset_path)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Reveal asset not found")
    return FileResponse(path=candidate)


def _resolve_run_path(run_id: str) -> Path:
    backend_root = Path(__file__).resolve().parents[3]
    run_manager = RunManager(backend_root / "runs")
    try:
        return run_manager.get_run_path_by_id(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


def _resolve_run_manager(run_path: Path) -> RunManager:
    backend_root = Path(__file__).resolve().parents[3]
    run_manager = RunManager(backend_root / "runs")
    run_manager.set_run_path(run_path)
    return run_manager


def _find_source_pdf_for_retry(run_path: Path) -> Path:
    input_dir = run_path / "input"
    if not input_dir.is_dir():
        raise HTTPException(status_code=400, detail="Unable to retry run: original input directory is missing")

    pdf_candidates = sorted(path for path in input_dir.glob("*.pdf") if path.is_file())
    if not pdf_candidates:
        raise HTTPException(status_code=400, detail="Unable to retry run: original input PDF is missing")

    source_pdf = next((path for path in pdf_candidates if path.name.lower() == "source.pdf"), pdf_candidates[0])
    return source_pdf


def _build_retry_configuration(run_path: Path, manifest: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    job_summary = (manifest.get("run_summary") or {}).get("job_summary", {})
    if not isinstance(job_summary, dict):
        job_summary = {}

    job_spec = _load_json(run_path / "input" / "job_spec.json") or {}

    presentation_style = job_spec.get("presentation_style") or job_summary.get("presentation_style") or "journal_club"
    audience = job_spec.get("audience") or job_summary.get("target_audience") or "research_specialists"
    language = job_spec.get("language") or job_summary.get("language") or "en"
    output_formats = job_spec.get("output_formats") or job_summary.get("output_formats") or ["reveal", "pptx"]

    if not isinstance(output_formats, list) or not output_formats:
        output_formats = ["reveal", "pptx"]
    output_formats = [str(item).strip() for item in output_formats if str(item).strip()]
    if not output_formats:
        output_formats = ["reveal", "pptx"]

    advanced_options = job_summary.get("advanced_options")
    if not isinstance(advanced_options, dict):
        advanced_options = {}

    if isinstance(job_spec.get("advanced_options"), dict):
        advanced_options = {**advanced_options, **job_spec.get("advanced_options")}

    repair_on_audit = bool(job_spec.get("repair_on_audit", job_summary.get("repair_on_audit", False)))

    workflow_options: dict[str, Any] = {
        "presentation_style": str(presentation_style),
        "audience": str(audience),
        "language": str(language),
        "output_formats": output_formats,
        "advanced_options": advanced_options,
    }
    return workflow_options, repair_on_audit


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _count_audit_findings(run_path: Path) -> int | None:
    for filename in ("audit_report_final.json", "audit_report_initial.json"):
        payload = _load_json(run_path / "audit" / filename)
        if payload is None:
            continue
        audits = payload.get("slide_audits", [])
        return sum(len(item.get("findings", [])) for item in audits if isinstance(item, dict))
    return None


def _resolve_child_path(*, base_dir: Path, candidate_path: str, run_path: Path) -> Path | None:
    if not candidate_path:
        return None

    candidate = Path(candidate_path)
    if not candidate.is_absolute():
        run_relative_candidate = (run_path / candidate).resolve()
        base_relative_candidate = (base_dir / candidate).resolve()
        candidate = run_relative_candidate if run_relative_candidate.is_file() else base_relative_candidate
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(base_dir)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    return candidate


def _reveal_roots(run_path: Path) -> list[Path]:
    return [
        (run_path / "presentation" / "reveal").resolve(),
        (run_path / "presentation" / "reveal_repaired").resolve(),
    ]


def _resolve_reveal_index_path(*, run_path: Path, selected_path: str | None) -> Path | None:
    roots = _reveal_roots(run_path)

    if selected_path:
        for root in roots:
            candidate = _resolve_child_path(base_dir=root, candidate_path=selected_path, run_path=run_path)
            if candidate is not None:
                return candidate

    for root in roots:
        default_index = root / "index.html"
        if default_index.is_file():
            return default_index

    return None


def _resolve_reveal_asset_path(*, run_path: Path, asset_path: str) -> Path | None:
    for root in _reveal_roots(run_path):
        assets_root = (root / "assets").resolve()
        candidate = _resolve_child_path(base_dir=assets_root, candidate_path=asset_path, run_path=run_path)
        if candidate is not None:
            return candidate
    return None


def _manifest_age_seconds(manifest_path: Path) -> float:
    if not manifest_path.is_file():
        return 0.0
    modified = datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=UTC)
    return max(0.0, (datetime.now(UTC) - modified).total_seconds())


def _finalize_stalled_manifest_if_needed(manifest: dict[str, Any], *, stale_seconds: float) -> tuple[dict[str, Any], bool]:
    status = str(manifest.get("status", "")).strip().lower()
    if status != "running":
        return manifest, False

    current_stage = str(manifest.get("current_stage", "")).strip()
    completed_stages = manifest.get("completed_stages", [])
    if not isinstance(completed_stages, list):
        completed_stages = []

    stage_entries = manifest.get("stages", [])
    if not isinstance(stage_entries, list):
        stage_entries = []

    has_running_entry = any(
        isinstance(entry, dict) and str(entry.get("status", "")).strip().lower() == "running"
        for entry in stage_entries
    )
    current_is_completed = bool(current_stage) and current_stage in completed_stages

    if stale_seconds < _STALLED_RUNNING_SECONDS or has_running_entry or not current_is_completed:
        return manifest, False

    updated = dict(manifest)
    errors = updated.get("errors", [])
    if not isinstance(errors, list):
        errors = []

    stall_message = (
        f"Run auto-finalized as failed after stalling post-{current_stage} "
        f"for {int(stale_seconds)}s without stage progress."
    )
    if stall_message not in errors:
        errors.append(stall_message)

    updated["errors"] = errors
    updated["status"] = "failed"
    updated["failed_stage"] = current_stage or "unknown"
    updated["finished_at"] = datetime.now(UTC).isoformat()
    return updated, True
