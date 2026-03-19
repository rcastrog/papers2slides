"""Job submission route handlers."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from app.api.schemas import JobSubmissionRequest, JobSubmissionResponse
from app.orchestrator.workflow import WorkflowCancelledError, run_workflow
from app.storage.run_manager import RunManager
from app.utils.error_summary import summarize_exception_for_logs

router = APIRouter(tags=["jobs"])


@router.post("/jobs", response_model=JobSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(request: Request, background_tasks: BackgroundTasks) -> JobSubmissionResponse:
    """Create a run, start workflow execution, and return run tracking URLs."""
    backend_root = Path(__file__).resolve().parents[3]
    runs_root = backend_root / "runs"
    run_manager = RunManager(runs_root)

    parsed = await _parse_job_submission(request)
    run_path = run_manager.create_run(slug="api-job")
    run_id = run_path.name

    input_pdf_path = _prepare_pdf_input(
        run_path=run_path,
        uploaded_file=parsed.get("uploaded_file"),
        source_url=parsed.get("source_url"),
    )

    queued_manifest = {
        "run_id": run_id,
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
        "run_summary": {},
    }
    run_manager.save_json("logs/run_manifest.json", queued_manifest)

    background_tasks.add_task(
        _execute_workflow,
        input_pdf_path,
        run_path,
        bool(parsed.get("repair_on_audit", True)),
        {
            "presentation_style": parsed.get("presentation_style"),
            "audience": parsed.get("audience"),
            "language": parsed.get("language"),
            "output_formats": parsed.get("output_formats"),
            "advanced_options": parsed.get("advanced_options") or {},
        },
    )

    return JobSubmissionResponse(
        run_id=run_id,
        status="queued",
        status_url=f"/runs/{run_id}",
        results_url=f"/runs/{run_id}/results",
    )


async def _parse_job_submission(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        output_formats = _parse_output_formats(form.get("output_formats"))
        return {
            "uploaded_file": form.get("pdf_file"),
            "source_url": _none_if_empty(form.get("source_url")),
            "presentation_style": form.get("presentation_style") or "journal_club",
            "audience": form.get("audience") or "research_specialists",
            "language": form.get("language") or "en",
            "output_formats": output_formats,
            "repair_on_audit": _parse_bool(form.get("repair_on_audit")) if form.get("repair_on_audit") is not None else True,
            "advanced_options": _parse_json_object(form.get("advanced_options")),
        }

    if "application/json" in content_type:
        payload = await request.json()
        model = JobSubmissionRequest.model_validate(payload)
        return {
            "uploaded_file": None,
            "source_url": model.source_url,
            "presentation_style": model.presentation_style,
            "audience": model.audience,
            "language": model.language,
            "output_formats": model.output_formats,
            "repair_on_audit": model.repair_on_audit,
            "advanced_options": model.advanced_options,
        }

    raise HTTPException(status_code=415, detail="Unsupported content type. Use multipart/form-data or application/json.")


def _prepare_pdf_input(run_path: Path, uploaded_file: Any, source_url: str | None) -> Path:
    input_dir = run_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    if uploaded_file is not None and getattr(uploaded_file, "filename", None):
        file_path = input_dir / (Path(uploaded_file.filename).name or "uploaded.pdf")
        file_path.write_bytes(uploaded_file.file.read())
        return file_path

    if source_url:
        target = input_dir / "source.pdf"
        try:
            urllib.request.urlretrieve(source_url, target)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to download source_url: {exc}") from exc
        return target

    raise HTTPException(status_code=400, detail="Either pdf_file upload or source_url is required.")


def _execute_workflow(
    pdf_path: Path,
    run_path: Path,
    repair_on_audit: bool,
    workflow_options: dict[str, Any] | None = None,
) -> None:
    backend_root = Path(__file__).resolve().parents[3]
    run_manager = RunManager(backend_root / "runs")

    running_manifest = {
        "run_id": run_path.name,
        "status": "running",
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
            "job_summary": {
                "presentation_style": workflow_options.get("presentation_style") if isinstance(workflow_options, dict) else None,
                "target_audience": workflow_options.get("audience") if isinstance(workflow_options, dict) else None,
                "language": workflow_options.get("language") if isinstance(workflow_options, dict) else None,
                "output_formats": workflow_options.get("output_formats") if isinstance(workflow_options, dict) else None,
                "advanced_options": (workflow_options.get("advanced_options") if isinstance(workflow_options, dict) else {}) or {},
                "repair_on_audit": repair_on_audit,
            }
        },
    }

    try:
        run_manager.set_run_path(run_path)
        run_manager.save_json("logs/run_manifest.json", running_manifest)
        run_workflow(
            pdf_path=pdf_path,
            repair_on_audit=repair_on_audit,
            run_path=run_path,
            workflow_options=workflow_options,
        )
    except WorkflowCancelledError:
        latest_manifest = run_manager.read_json("logs/run_manifest.json") or {}
        checkpoint_state = latest_manifest.get("checkpoint_state")
        if not isinstance(checkpoint_state, dict):
            checkpoint_state = {}
        checkpoint_state["cancelled"] = True

        cancelled_manifest = {
            **running_manifest,
            **latest_manifest,
            "status": "cancelled",
            "checkpoint_state": checkpoint_state,
        }
        run_manager.save_json("logs/run_manifest.json", cancelled_manifest)
        run_manager.save_json(
            "logs/workflow_summary.json",
            {
                "run_id": run_path.name,
                "run_path": str(run_path),
                "status": "cancelled",
                "completed_stages": cancelled_manifest.get("completed_stages", []),
            },
        )
    except Exception as exc:
        failed_manifest = _build_failed_manifest(run_path=run_path, fallback=running_manifest, error=exc)
        error_summary = summarize_exception_for_logs(exc)
        run_manager.save_json("logs/run_manifest.json", failed_manifest)
        run_manager.save_json(
            "logs/workflow_summary.json",
            {
                "run_id": run_path.name,
                "run_path": str(run_path),
                "status": "failed",
                "error": error_summary,
                "completed_stages": failed_manifest.get("completed_stages", []),
            },
        )


def _build_failed_manifest(run_path: Path, fallback: dict[str, Any], error: Exception) -> dict[str, Any]:
    latest_manifest = _load_json_dict(run_path / "logs" / "run_manifest.json")
    base = {**fallback, **latest_manifest}

    existing_errors = base.get("errors", [])
    if not isinstance(existing_errors, list):
        existing_errors = []

    error_summary = summarize_exception_for_logs(error)

    failed_manifest = {
        **base,
        "status": "failed",
        "current_stage": base.get("current_stage", "A0"),
        "errors": [*existing_errors, error_summary],
    }
    failed_manifest["failed_stage"] = failed_manifest.get("current_stage", "A0")
    return failed_manifest


def _load_json_dict(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _none_if_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_bool(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _parse_output_formats(value: Any) -> list[str]:
    if value is None:
        return ["reveal", "pptx"]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    text = str(value).strip()
    if not text:
        return ["reveal", "pptx"]
    return [item.strip() for item in text.split(",") if item.strip()]


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"advanced_options is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="advanced_options must be a JSON object")
    return parsed
