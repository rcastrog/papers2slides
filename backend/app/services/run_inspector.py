"""Run inspector service for stage and artifact introspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Read-only allowlist for artifact browsing.
KNOWN_ARTIFACT_PATHS: dict[str, str] = {
    "run_manifest": "logs/run_manifest.json",
    "workflow_summary": "logs/workflow_summary.json",
    "results_summary": "logs/results_summary.json",
    "job_spec": "input/job_spec.json",
    "paper_parse_result": "analysis/paper_parse_result.json",
    "artifact_manifest": "artifacts/artifact_manifest.json",
    "extracted_assets": "artifacts/source/extracted_assets.json",
    "asset_map": "artifacts/source/asset_map.json",
    "reference_index": "references/reference_index.json",
    "presentation_plan": "presentation/presentation_plan.json",
    "speaker_notes": "presentation/speaker_notes.json",
    "generated_visuals": "presentation/generated_visuals.json",
    "reveal_render_plan": "presentation/reveal_render_plan.json",
    "reveal_render_result": "presentation/reveal_render_result.json",
    "pptx_build_plan": "presentation/pptx_build_plan.json",
    "pptx_build_result": "presentation/pptx_build_result.json",
    "audit_report_initial": "audit/audit_report_initial.json",
    "audit_report_final": "audit/audit_report_final.json",
    "reveal_index_html": "presentation/reveal/index.html",
}


class RunInspector:
    """Normalizes run-level status, stage, and artifact inspection data."""

    def __init__(self, run_path: Path) -> None:
        self._run_path = run_path

    def get_run_inspection(self) -> dict[str, Any]:
        manifest = self._load_json("logs/run_manifest.json") or {}
        workflow_summary = self._load_json("logs/workflow_summary.json") or {}

        stages = manifest.get("stages", [])
        if not isinstance(stages, list):
            stages = []

        quality_signals = {
            "deck_risk_level": self._pick(
                manifest.get("run_summary", {}).get("deck_risk_level") if isinstance(manifest.get("run_summary"), dict) else None,
                workflow_summary.get("deck_risk_level_final"),
            ),
            "unresolved_high_severity_findings_count": self._pick(
                manifest.get("run_summary", {}).get("unresolved_high_severity_findings_count")
                if isinstance(manifest.get("run_summary"), dict)
                else None,
                workflow_summary.get("unresolved_high_severity_findings_count"),
                0,
            ),
            "fallback_stage_count": self._pick(
                manifest.get("run_summary", {}).get("fallback_stage_count") if isinstance(manifest.get("run_summary"), dict) else None,
                self._count_fallback_stages(stages),
            ),
            "audit_findings_count": self._pick(
                manifest.get("run_summary", {}).get("audit_findings_count") if isinstance(manifest.get("run_summary"), dict) else None,
                self._count_audit_findings(),
            ),
        }

        artifacts = self._build_artifact_index(manifest)
        extracted_assets = self.get_extracted_assets()
        asset_map = self.get_asset_map()

        return {
            "run_id": manifest.get("run_id", self._run_path.name),
            "status": manifest.get("status", "unknown"),
            "current_stage": manifest.get("current_stage", "unknown"),
            "llm_mode": manifest.get("llm_mode"),
            "llm_mode_reason": manifest.get("llm_mode_reason"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "duration_ms": manifest.get("duration_ms"),
            "warning_count": len(manifest.get("warnings", [])) if isinstance(manifest.get("warnings"), list) else 0,
            "error_count": len(manifest.get("errors", [])) if isinstance(manifest.get("errors"), list) else 0,
            "completed_stages": manifest.get("completed_stages", []),
            "stages": stages,
            "quality_signals": quality_signals,
            "artifacts": artifacts,
            "extracted_assets_summary": {
                "count": extracted_assets["count"],
                "warning_count": len(extracted_assets["warnings"]),
            },
            "asset_map_summary": {
                "entry_count": asset_map["entry_count"],
                "resolved_count": asset_map["resolved_count"],
                "unresolved_count": asset_map["unresolved_count"],
                "ambiguous_count": asset_map["ambiguous_count"],
                "warning_count": len(asset_map["warnings"]),
            },
            "warnings": manifest.get("warnings", []),
            "errors": manifest.get("errors", []),
        }

    def get_extracted_assets(self) -> dict[str, Any]:
        """Return normalized extracted source assets for inspector and API payloads."""
        payload = self._load_json("artifacts/source/extracted_assets.json") or {}
        assets_raw = payload.get("extracted_assets", [])
        warnings_raw = payload.get("warnings", [])

        assets: list[dict[str, Any]] = []
        if isinstance(assets_raw, list):
            for item in assets_raw:
                if not isinstance(item, dict):
                    continue
                asset_id = str(item.get("asset_id", "")).strip()
                file_path = str(item.get("file_path", "")).strip()
                if not asset_id or not file_path:
                    continue

                resolved, normalized = self._resolve_relative_file(file_path)
                if resolved is None or normalized is None:
                    continue

                assets.append(
                    {
                        "asset_id": asset_id,
                        "relative_path": normalized,
                        "page_number": item.get("page_number"),
                        "extraction_method": str(item.get("extraction_method", "unknown")),
                        "width": item.get("width"),
                        "height": item.get("height"),
                        "notes": item.get("notes", []) if isinstance(item.get("notes", []), list) else [],
                    }
                )

        warnings = [str(item) for item in warnings_raw] if isinstance(warnings_raw, list) else []
        return {
            "assets": assets,
            "warnings": warnings,
            "count": len(assets),
        }

    def get_asset_map(self) -> dict[str, Any]:
        """Return normalized asset-map decisions and visual-level resolution report."""
        payload = self._load_json("artifacts/source/asset_map.json") or {}
        entries_raw = payload.get("entries", [])
        warnings_raw = payload.get("warnings", [])

        entries: list[dict[str, Any]] = []
        if isinstance(entries_raw, list):
            for item in entries_raw:
                if not isinstance(item, dict):
                    continue

                resolved_path = str(item.get("resolved_path", "")).strip()
                selected_asset_id = str(item.get("selected_asset_id", "")).strip() or None
                normalized_resolved_path = self._normalize_existing_path(resolved_path) if resolved_path else None

                status = str(item.get("status", "")).strip().lower()
                if status not in {"resolved", "unresolved", "ambiguous"}:
                    if normalized_resolved_path:
                        status = "resolved"
                    else:
                        confidence = str(item.get("confidence", "")).strip().lower()
                        status = "ambiguous" if confidence == "ambiguous" else "unresolved"

                entries.append(
                    {
                        "artifact_id": str(item.get("artifact_id", "")),
                        "page_numbers": item.get("page_numbers", []) if isinstance(item.get("page_numbers", []), list) else [],
                        "candidate_asset_ids": item.get("candidate_asset_ids", [])
                        if isinstance(item.get("candidate_asset_ids", []), list)
                        else [],
                        "selected_asset_id": selected_asset_id,
                        "resolved_path": normalized_resolved_path,
                        "resolution_status": status,
                        "confidence": str(item.get("confidence", "")),
                        "decision_reason": str(item.get("decision_reason", "")),
                        "warnings": item.get("warnings", []) if isinstance(item.get("warnings", []), list) else [],
                        "matching_signals": item.get("matching_signals", {})
                        if isinstance(item.get("matching_signals", {}), dict)
                        else {},
                    }
                )

        warnings = [str(item) for item in warnings_raw] if isinstance(warnings_raw, list) else []
        resolved_count = sum(1 for entry in entries if entry["resolution_status"] == "resolved")
        unresolved_count = sum(1 for entry in entries if entry["resolution_status"] == "unresolved")
        ambiguous_count = sum(1 for entry in entries if entry["resolution_status"] == "ambiguous")

        return {
            "entries": entries,
            "warnings": warnings,
            "entry_count": len(entries),
            "resolved_count": resolved_count,
            "unresolved_count": unresolved_count,
            "ambiguous_count": ambiguous_count,
            "visual_resolution": self.get_visual_resolution_report(),
        }

    def get_visual_resolution_report(self) -> list[dict[str, Any]]:
        """Return per-planned-visual resolution outcomes from final reveal output."""
        plan_payload = self._load_json("presentation/presentation_plan_repaired.json") or self._load_json("presentation/presentation_plan.json")
        reveal_payload = self._load_json("presentation/reveal_render_result_repaired.json") or self._load_json("presentation/reveal_render_result.json")

        if not isinstance(plan_payload, dict) or not isinstance(reveal_payload, dict):
            return []

        reveal_index: dict[tuple[int, str], dict[str, Any]] = {}
        slide_results = reveal_payload.get("slide_render_results", [])
        if isinstance(slide_results, list):
            for slide_result in slide_results:
                if not isinstance(slide_result, dict):
                    continue
                slide_number = int(slide_result.get("slide_number", 0) or 0)
                assets_used = slide_result.get("assets_used", [])
                if not isinstance(assets_used, list):
                    continue
                for asset in assets_used:
                    if not isinstance(asset, dict):
                        continue
                    asset_id = str(asset.get("asset_id", "")).strip()
                    if not asset_id or slide_number <= 0:
                        continue
                    reveal_index[(slide_number, asset_id)] = asset

        rows: list[dict[str, Any]] = []
        slides = plan_payload.get("slides", [])
        if not isinstance(slides, list):
            return rows

        for slide in slides:
            if not isinstance(slide, dict):
                continue
            slide_number = int(slide.get("slide_number", 0) or 0)
            slide_title = str(slide.get("title", ""))
            visuals = slide.get("visuals", [])
            if not isinstance(visuals, list):
                continue
            for visual in visuals:
                if not isinstance(visual, dict):
                    continue
                asset_id = str(visual.get("asset_id", "")).strip()
                source_origin = str(visual.get("source_origin", ""))
                if not asset_id or asset_id.lower() == "none" or str(visual.get("visual_type", "")) == "text_only":
                    continue

                reveal_asset = reveal_index.get((slide_number, asset_id), {})
                resolved_path_raw = str(reveal_asset.get("resolved_path", "")).strip()
                resolved_path = self._normalize_existing_path(resolved_path_raw) if resolved_path_raw else None
                fallback_used = not bool(resolved_path)

                rows.append(
                    {
                        "slide_number": slide_number,
                        "slide_title": slide_title,
                        "requested_asset_id": asset_id,
                        "source_origin": source_origin,
                        "resolved_path": resolved_path,
                        "fallback_used": fallback_used,
                        "provenance_note": "resolved_from_asset_map_or_discovery"
                        if not fallback_used
                        else "fallback_placeholder_or_generated_visual",
                    }
                )
        return rows

    def get_artifact_payload(self, artifact_key: str) -> dict[str, Any]:
        artifact_index = self._build_artifact_index(self._load_json("logs/run_manifest.json") or {})
        relative_path = artifact_index.get(artifact_key)
        if relative_path is None:
            raise KeyError(f"Unknown artifact key: {artifact_key}")

        target, normalized = self._resolve_relative_file(relative_path)
        if target is None or normalized is None:
            raise FileNotFoundError(f"Artifact not found: {artifact_key}")

        suffix = target.suffix.lower()
        if suffix == ".json":
            content = json.loads(target.read_text(encoding="utf-8"))
            content_kind = "json"
        elif suffix in {".txt", ".md", ".log", ".html", ".csv"}:
            content = target.read_text(encoding="utf-8")
            content_kind = "text"
        else:
            # Binary artifacts are available through /download endpoint, not inspector payload.
            content = None
            content_kind = "binary"

        return {
            "artifact_key": artifact_key,
            "relative_path": normalized,
            "content_kind": content_kind,
            "content": content,
        }

    def _build_artifact_index(self, manifest: dict[str, Any]) -> dict[str, str]:
        merged = dict(KNOWN_ARTIFACT_PATHS)
        manifest_artifacts = manifest.get("artifacts", {})
        if isinstance(manifest_artifacts, dict):
            merged.update({str(key): str(value) for key, value in manifest_artifacts.items()})

        available: dict[str, str] = {}
        for key, relative_path in merged.items():
            resolved, normalized = self._resolve_relative_file(relative_path)
            if resolved is not None and normalized is not None:
                available[key] = normalized
        return available

    def _resolve_relative_file(self, relative_path: str) -> tuple[Path | None, str | None]:
        raw_candidate = Path(relative_path)
        candidate = raw_candidate.resolve() if raw_candidate.is_absolute() else (self._run_path / raw_candidate).resolve()
        try:
            normalized = str(candidate.relative_to(self._run_path.resolve())).replace("\\", "/")
        except ValueError:
            return None, None
        return (candidate, normalized) if candidate.is_file() else (None, None)

    def _normalize_existing_path(self, candidate_path: str) -> str | None:
        """Return run-relative normalized path when candidate exists inside current run."""
        resolved, normalized = self._resolve_relative_file(candidate_path)
        if resolved is None or normalized is None:
            return None
        return normalized

    def _load_json(self, relative_path: str) -> dict[str, Any] | None:
        target, _ = self._resolve_relative_file(relative_path)
        if target is None:
            return None
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def _count_fallback_stages(self, stages: list[Any]) -> int:
        count = 0
        for stage in stages:
            if isinstance(stage, dict) and stage.get("fallback_used"):
                count += 1
        return count

    def _count_audit_findings(self) -> int | None:
        for relative_path in ("audit/audit_report_final.json", "audit/audit_report_initial.json"):
            payload = self._load_json(relative_path)
            if payload is None:
                continue
            audits = payload.get("slide_audits", [])
            if not isinstance(audits, list):
                continue
            total = 0
            for item in audits:
                if isinstance(item, dict):
                    findings = item.get("findings", [])
                    if isinstance(findings, list):
                        total += len(findings)
            return total
        return None

    @staticmethod
    def _pick(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None
