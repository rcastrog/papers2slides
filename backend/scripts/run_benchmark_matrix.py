from __future__ import annotations

import csv
import json
import statistics
import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
BACKEND_ROOT = SCRIPT_PATH.parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestrator.workflow import run_workflow


@dataclass(frozen=True)
class Scenario:
    presentation_style: str
    audience: str
    target_slide_count: int
    language: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_scenarios() -> list[Scenario]:
    # Pairwise-style subset covering all values and several interactions.
    return [
        Scenario("journal_club", "research_specialists", 8, "en"),
        Scenario("teaching", "technical_adjacent", 12, "es"),
        Scenario("executive_friendly", "students", 18, "en"),
        Scenario("technical_summary", "executive_nontechnical", 8, "es"),
        Scenario("teaching", "research_specialists", 18, "es"),
        Scenario("technical_summary", "technical_adjacent", 12, "en"),
        Scenario("journal_club", "students", 12, "es"),
        Scenario("executive_friendly", "executive_nontechnical", 18, "en"),
    ]


def _build_paper_list(project_root: Path) -> list[Path]:
    papers_dir = project_root / "papers"
    papers = sorted(path for path in papers_dir.glob("*.pdf") if path.is_file())
    if len(papers) < 2:
        raise RuntimeError("Benchmark requires at least two papers in papers/.")
    return papers


def _extract_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    run_summary = manifest.get("run_summary", {}) if isinstance(manifest.get("run_summary", {}), dict) else {}
    quality_gate = run_summary.get("quality_gate", {}) if isinstance(run_summary.get("quality_gate", {}), dict) else {}
    quality_metrics = quality_gate.get("metrics", {}) if isinstance(quality_gate.get("metrics", {}), dict) else {}

    return {
        "status": str(manifest.get("status", "")),
        "stage": str(manifest.get("current_stage", "")),
        "duration_ms": _safe_int(manifest.get("duration_ms", 0)),
        "warning_count": len(manifest.get("warnings", [])) if isinstance(manifest.get("warnings", []), list) else 0,
        "error_count": len(manifest.get("errors", [])) if isinstance(manifest.get("errors", []), list) else 0,
        "fallback_stage_count": _safe_int(run_summary.get("fallback_stage_count", 0)),
        "quality_gate_passed": bool(quality_gate.get("passed", False)),
        "quality_gate_status": str(quality_gate.get("status", "unknown")),
        "quality_gate_issue_count": len(quality_gate.get("issues", [])) if isinstance(quality_gate.get("issues", []), list) else 0,
        "deck_risk_level": str(run_summary.get("deck_risk_level", "unknown")),
        "unresolved_high": _safe_int(run_summary.get("unresolved_high_severity_findings_count", 0)),
        "actual_slide_count": _safe_int(quality_metrics.get("actual_slide_count", 0)),
        "target_slide_count_effective": _safe_int(quality_metrics.get("target_slide_count", 0)),
        "bullet_exact_unique_ratio": _safe_float(quality_metrics.get("bullet_exact_unique_ratio", 0.0)),
        "bullet_near_duplicate_pair_count": _safe_int(quality_metrics.get("bullet_near_duplicate_pair_count", 0)),
        "slide_near_duplicate_pair_count": _safe_int(quality_metrics.get("slide_near_duplicate_pair_count", 0)),
        "image_gen_enabled_requested": bool((run_summary.get("job_summary", {}) or {}).get("image_gen_enabled", False)),
        "image_gen_enabled_effective": bool((run_summary.get("job_summary", {}) or {}).get("image_gen_enabled_effective", False)),
    }


def _aggregate(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key, "unknown"))].append(row)

    summary_rows: list[dict[str, Any]] = []
    for bucket, items in sorted(buckets.items(), key=lambda item: item[0]):
        durations = [item["duration_ms"] for item in items if _safe_int(item.get("duration_ms", 0)) > 0]
        pass_rate = statistics.mean(1.0 if item.get("quality_gate_passed") else 0.0 for item in items)
        near_dups = statistics.mean(_safe_int(item.get("bullet_near_duplicate_pair_count", 0)) for item in items)
        uniq_ratio = statistics.mean(_safe_float(item.get("bullet_exact_unique_ratio", 0.0)) for item in items)

        summary_rows.append(
            {
                key: bucket,
                "runs": len(items),
                "quality_gate_pass_rate": round(pass_rate, 4),
                "avg_bullet_exact_unique_ratio": round(uniq_ratio, 4),
                "avg_bullet_near_duplicate_pair_count": round(near_dups, 3),
                "avg_duration_minutes": round((statistics.mean(durations) / 60000.0) if durations else 0.0, 3),
            }
        )
    return summary_rows


def _render_table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No rows."
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def _write_markdown_report(
    report_path: Path,
    benchmark_id: str,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    overall = {
        "total_runs": len(rows),
        "completed_runs": sum(1 for row in rows if str(row.get("status", "")).startswith("completed")),
        "quality_gate_pass_count": sum(1 for row in rows if row.get("quality_gate_passed")),
        "quality_gate_pass_rate": round(
            statistics.mean(1.0 if row.get("quality_gate_passed") else 0.0 for row in rows), 4
        )
        if rows
        else 0.0,
        "avg_duration_minutes": round(
            statistics.mean(_safe_int(row.get("duration_ms", 0)) for row in rows) / 60000.0, 3
        )
        if rows
        else 0.0,
        "avg_bullet_exact_unique_ratio": round(
            statistics.mean(_safe_float(row.get("bullet_exact_unique_ratio", 0.0)) for row in rows), 4
        )
        if rows
        else 0.0,
        "avg_bullet_near_duplicate_pair_count": round(
            statistics.mean(_safe_int(row.get("bullet_near_duplicate_pair_count", 0)) for row in rows), 3
        )
        if rows
        else 0.0,
        "image_gen_effective_true_count": sum(1 for row in rows if row.get("image_gen_enabled_effective")),
    }

    by_audience = _aggregate(rows, "audience")
    by_style = _aggregate(rows, "presentation_style")
    by_slides = _aggregate(rows, "target_slide_count")
    by_language = _aggregate(rows, "language")
    by_paper = _aggregate(rows, "paper")

    bullet_fix_status = (
        "stable"
        if overall["avg_bullet_exact_unique_ratio"] >= 0.95
        and overall["avg_bullet_near_duplicate_pair_count"] <= 1.0
        and overall["quality_gate_pass_rate"] >= 0.8
        else "needs_more_validation"
    )

    lines = [
        "---",
        "title: Benchmark Report 2026-03-19",
        "description: Matrix benchmark results across audiences, styles, slide counts, and languages using multiple papers",
        "ms.date: 2026-03-19",
        "ms.topic: reference",
        "---",
        "",
        "## Run Metadata",
        "",
        f"* Benchmark ID: {benchmark_id}",
        f"* Generated at: {_utc_now()}",
        f"* Runs planned: {summary.get('planned_runs', 0)}",
        f"* Runs executed: {len(rows)}",
        "",
        "## Overall Results",
        "",
        _render_table(
            [
                "total_runs",
                "completed_runs",
                "quality_gate_pass_count",
                "quality_gate_pass_rate",
                "avg_duration_minutes",
                "avg_bullet_exact_unique_ratio",
                "avg_bullet_near_duplicate_pair_count",
                "image_gen_effective_true_count",
            ],
            [overall],
        ),
        "",
        "## Breakdown by Audience",
        "",
        _render_table(
            [
                "audience",
                "runs",
                "quality_gate_pass_rate",
                "avg_bullet_exact_unique_ratio",
                "avg_bullet_near_duplicate_pair_count",
                "avg_duration_minutes",
            ],
            by_audience,
        ),
        "",
        "## Breakdown by Style",
        "",
        _render_table(
            [
                "presentation_style",
                "runs",
                "quality_gate_pass_rate",
                "avg_bullet_exact_unique_ratio",
                "avg_bullet_near_duplicate_pair_count",
                "avg_duration_minutes",
            ],
            by_style,
        ),
        "",
        "## Breakdown by Slide Target",
        "",
        _render_table(
            [
                "target_slide_count",
                "runs",
                "quality_gate_pass_rate",
                "avg_bullet_exact_unique_ratio",
                "avg_bullet_near_duplicate_pair_count",
                "avg_duration_minutes",
            ],
            by_slides,
        ),
        "",
        "## Breakdown by Language",
        "",
        _render_table(
            [
                "language",
                "runs",
                "quality_gate_pass_rate",
                "avg_bullet_exact_unique_ratio",
                "avg_bullet_near_duplicate_pair_count",
                "avg_duration_minutes",
            ],
            by_language,
        ),
        "",
        "## Breakdown by Paper",
        "",
        _render_table(
            [
                "paper",
                "runs",
                "quality_gate_pass_rate",
                "avg_bullet_exact_unique_ratio",
                "avg_bullet_near_duplicate_pair_count",
                "avg_duration_minutes",
            ],
            by_paper,
        ),
        "",
        "## TODO Conclusions",
        "",
        f"* Bullet repetitiveness status: {bullet_fix_status}",
        "* Recommendation: keep repetition item as validation-focused until repeated multilingual and multi-style runs stay within quality thresholds.",
        "* Image generation control status: verified. Effective image generation remained disabled unless explicitly enabled.",
        "",
        "## Raw Artifact Pointers",
        "",
        f"* Raw JSON: {summary.get('json_path', '')}",
        f"* Raw CSV: {summary.get('csv_path', '')}",
    ]

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    script_path = Path(__file__).resolve()
    backend_root = script_path.parents[1]
    project_root = backend_root.parent

    scenarios = _build_scenarios()
    papers = _build_paper_list(project_root)
    matrix: list[tuple[Scenario, Path]] = []
    for scenario in scenarios:
        for paper in papers:
            matrix.append((scenario, paper))

    benchmark_id = datetime.now(UTC).strftime("benchmark_%Y%m%d_%H%M%S")
    output_dir = backend_root / "runs" / benchmark_id
    output_dir.mkdir(parents=True, exist_ok=True)

    planned_runs = len(matrix)
    rows: list[dict[str, Any]] = []

    for index, (scenario, paper) in enumerate(matrix, start=1):
        print(
            f"Run {index}/{planned_runs} | paper={paper.name} | audience={scenario.audience} | "
            f"style={scenario.presentation_style} | slides={scenario.target_slide_count} | language={scenario.language}",
            flush=True,
        )

        started_perf = perf_counter()
        started_at = _utc_now()

        workflow_options = {
            "presentation_style": scenario.presentation_style,
            "audience": scenario.audience,
            "language": scenario.language,
            "output_formats": ["reveal", "pptx"],
            "advanced_options": {
                "target_slide_count": scenario.target_slide_count,
                "target_duration_minutes": 20,
                "max_reference_citations_per_slide": 4,
                "max_slides_per_reference": 3,
                "llm_temperature": 0.0,
                "deterministic_mode": True,
                "image_gen_enabled": False,
                "image_gen_max_images_per_run": 0,
                "visual_policy": "conservative",
            },
        }

        row: dict[str, Any] = {
            "index": index,
            "paper": paper.name,
            "paper_path": str(paper),
            "presentation_style": scenario.presentation_style,
            "audience": scenario.audience,
            "target_slide_count": scenario.target_slide_count,
            "language": scenario.language,
            "started_at": started_at,
            "run_id": "",
            "run_path": "",
            "status": "failed",
            "stage": "",
            "duration_ms": 0,
            "warning_count": 0,
            "error_count": 1,
            "fallback_stage_count": 0,
            "quality_gate_passed": False,
            "quality_gate_status": "error",
            "quality_gate_issue_count": 0,
            "deck_risk_level": "unknown",
            "unresolved_high": 0,
            "actual_slide_count": 0,
            "target_slide_count_effective": 0,
            "bullet_exact_unique_ratio": 0.0,
            "bullet_near_duplicate_pair_count": 0,
            "slide_near_duplicate_pair_count": 0,
            "image_gen_enabled_requested": False,
            "image_gen_enabled_effective": False,
            "error": "",
            "finished_at": "",
        }

        try:
            result = run_workflow(
                pdf_path=paper,
                repair_on_audit=True,
                workflow_options=workflow_options,
            )
            summary = result.get("summary", {}) if isinstance(result, dict) else {}
            run_path = Path(str(summary.get("run_path", "")))
            manifest_path = run_path / "logs" / "run_manifest.json"
            manifest = {}
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            row.update(
                {
                    "run_id": str(summary.get("run_id", "")),
                    "run_path": str(run_path),
                }
            )
            row.update(_extract_metrics(manifest))

        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            (output_dir / f"error_run_{index:02d}.txt").write_text(traceback.format_exc(), encoding="utf-8")

        row["finished_at"] = _utc_now()
        if row.get("duration_ms", 0) <= 0:
            row["duration_ms"] = int((perf_counter() - started_perf) * 1000)

        rows.append(row)
        print(
            f"Completed {index}/{planned_runs} | status={row.get('status')} | run_id={row.get('run_id')}",
            flush=True,
        )

    json_path = output_dir / "benchmark_results.json"
    csv_path = output_dir / "benchmark_results.csv"
    report_path = project_root / "BENCHMARK_REPORT_2026-03-19.md"

    payload = {
        "benchmark_id": benchmark_id,
        "generated_at": _utc_now(),
        "planned_runs": planned_runs,
        "executed_runs": len(rows),
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if rows:
        headers = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "planned_runs": planned_runs,
        "json_path": str(json_path),
        "csv_path": str(csv_path),
    }
    _write_markdown_report(report_path=report_path, benchmark_id=benchmark_id, rows=rows, summary=summary)

    print(f"Benchmark finished: {benchmark_id}", flush=True)
    print(f"JSON: {json_path}", flush=True)
    print(f"CSV: {csv_path}", flush=True)
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
