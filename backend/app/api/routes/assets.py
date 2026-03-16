"""Routes for extracted source assets and asset-map decision introspection."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.run_inspector import RunInspector
from app.storage.run_manager import RunManager

router = APIRouter(tags=["assets"])


@router.get("/runs/{run_id}/assets")
def get_run_assets(run_id: str) -> dict[str, object]:
    """Return normalized extracted source assets for a run."""
    run_path = _resolve_run_path(run_id)
    inspector = RunInspector(run_path)
    payload = inspector.get_extracted_assets()

    assets = []
    for item in payload["assets"]:
        asset_id = str(item.get("asset_id", "")).strip()
        assets.append(
            {
                **item,
                "download_url": f"/runs/{run_id}/assets/{asset_id}" if asset_id else None,
            }
        )

    return {
        "run_id": run_id,
        "assets": assets,
        "warnings": payload["warnings"],
        "count": payload["count"],
    }


@router.get("/runs/{run_id}/asset-map")
def get_run_asset_map(run_id: str) -> dict[str, object]:
    """Return normalized asset-map decisions for a run."""
    run_path = _resolve_run_path(run_id)
    inspector = RunInspector(run_path)
    payload = inspector.get_asset_map()

    return {
        "run_id": run_id,
        **payload,
    }


@router.get("/runs/{run_id}/assets/{asset_id}")
def download_asset(run_id: str, asset_id: str) -> FileResponse:
    """Stream an extracted source asset by id when available in run artifacts."""
    run_path = _resolve_run_path(run_id)
    inspector = RunInspector(run_path)
    payload = inspector.get_extracted_assets()

    relative_path = None
    for item in payload["assets"]:
        if str(item.get("asset_id", "")) == asset_id:
            relative_path = str(item.get("relative_path", ""))
            break

    if not relative_path:
        raise HTTPException(status_code=404, detail="Asset not found")

    candidate = (run_path / relative_path).resolve()
    try:
        candidate.relative_to(run_path.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid asset path") from exc

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Asset file not found")

    return FileResponse(path=candidate, filename=candidate.name)


def _resolve_run_path(run_id: str) -> Path:
    backend_root = Path(__file__).resolve().parents[3]
    run_manager = RunManager(backend_root / "runs")
    try:
        return run_manager.get_run_path_by_id(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
