"""Run artifact inspection routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.services.run_inspector import RunInspector
from app.storage.run_manager import RunManager

router = APIRouter(tags=["artifacts"])


@router.get("/runs/{run_id}/inspect")
def inspect_run(run_id: str) -> dict[str, object]:
    """Return run summary plus stage-by-stage metadata and available artifacts."""
    run_path = _resolve_run_path(run_id)
    inspector = RunInspector(run_path)
    return inspector.get_run_inspection()


@router.get("/runs/{run_id}/artifacts/{artifact_key}")
def read_artifact(run_id: str, artifact_key: str) -> dict[str, object]:
    """Return read-only artifact payload for known artifact keys."""
    run_path = _resolve_run_path(run_id)
    inspector = RunInspector(run_path)
    try:
        return inspector.get_artifact_payload(artifact_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read artifact: {exc}") from exc


def _resolve_run_path(run_id: str) -> Path:
    backend_root = Path(__file__).resolve().parents[3]
    run_manager = RunManager(backend_root / "runs")
    try:
        return run_manager.get_run_path_by_id(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
