"""Run status and results route handlers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.schemas import RunResultsResponse, RunStatusResponse
from app.orchestrator.workflow import recover_a11_only
from app.services.run_inspector import RunInspector
from app.storage.run_manager import RunManager

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str) -> RunStatusResponse:
    """Return current run status from run manifest (source of truth)."""
    run_path = _resolve_run_path(run_id)

    manifest = _load_json(run_path / "logs" / "run_manifest.json")
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

    audit_findings_count = _count_audit_findings(run_path)
    warnings = manifest.get("warnings", [])
    stage_entries = manifest.get("stages", [])
    if not isinstance(stage_entries, list):
        stage_entries = []
    fallback_stage_count = sum(1 for stage in stage_entries if isinstance(stage, dict) and stage.get("fallback_used"))

    return RunStatusResponse(
        run_id=manifest.get("run_id", run_id),
        status=manifest.get("status", "running"),
        current_stage=manifest.get("current_stage", "unknown"),
        completed_stages=manifest.get("completed_stages", []),
        warnings=warnings,
        warning_count=len(warnings),
        key_artifact_paths=manifest.get("artifacts", {}),
        checkpoint_state=manifest.get("checkpoint_state", {}),
        audit_findings_count=audit_findings_count,
        stage_count=len(stage_entries),
        fallback_stage_count=fallback_stage_count,
        total_duration_ms=manifest.get("duration_ms"),
        job_summary=(manifest.get("run_summary", {}) or {}).get("job_summary", {}),
    )


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

    return payload


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
    if not selected:
        raise HTTPException(status_code=404, detail="Reveal output not found")

    reveal_root = (run_path / "presentation" / "reveal").resolve()
    candidate = _resolve_child_path(base_dir=reveal_root, candidate_path=selected, run_path=run_path)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Reveal output not found")

    return FileResponse(path=candidate, media_type="text/html")


@router.get("/runs/{run_id}/reveal/assets/{asset_path:path}")
def get_reveal_asset(run_id: str, asset_path: str) -> FileResponse:
    """Serve reveal assets while preventing path traversal."""
    run_path = _resolve_run_path(run_id)
    assets_root = (run_path / "presentation" / "reveal" / "assets").resolve()
    candidate = _resolve_child_path(base_dir=assets_root, candidate_path=asset_path, run_path=run_path)
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
