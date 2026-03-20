"""Sequential local-first workflow for A0->A11 with one optional repair cycle."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import shutil
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from dataclasses import replace
import urllib.request
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.agents.artifact_agent import ArtifactExtractionAgent
from app.agents.auditor_agent import AuditorAgent
from app.agents.citation_repair_agent import CitationRepairAgent
from app.agents.intake_agent import IntakeAgent
from app.agents.notes_agent import SpeakerNotesAgent
from app.agents.notes_repair_agent import NotesRepairAgent
from app.agents.parser_agent import ParserAgent
from app.agents.planner_agent import PresentationPlannerAgent
from app.agents.pptx_agent import PPTXBuilderAgent
from app.agents.reference_retrieval_agent import ReferenceRetrievalAgent
from app.agents.reference_summary_agent import ReferenceSummaryAgent
from app.agents.reveal_agent import RevealBuilderAgent
from app.agents.section_analysis_agent import SectionAnalysisAgent
from app.agents.slide_repair_agent import SlideRepairAgent
from app.agents.translation_repair_agent import TranslationRepairAgent
from app.agents.visual_agent import VisualGenerationAgent
from app.agents.visual_repair_agent import VisualRepairAgent
from app.config import LLMSettings
from app.models.artifact_manifest import ArtifactManifest
from app.models.audit_report import AuditReport
from app.models.generated_visuals import GeneratedVisuals
from app.models.pptx_result import PPTXBuildResult
from app.models.presentation_plan import PresentationPlan
from app.models.reference_index import ReferenceIndex
from app.models.reference_summary import ReferenceSummary
from app.models.speaker_notes import SpeakerNotes
from app.services.arxiv_client import ArxivClient
from app.services.asset_mapper import AssetMapper
from app.services.image_generation_service import ImageGenerationSettings, OpenAIConceptualImageGenerator
from app.services.llm_client import AzureOpenAIChatTransport, FallbackOnAuthErrorTransport, LLMClient, OpenAIChatTransport, SequentialMockTransport
from app.services.pdf_artifact_extractor import PDFArtifactExtractor
from app.services.pdf_parser import PDFParseOutput, PDFParser
from app.services.prompt_loader import PromptLoader
from app.services.reference_parser import ReferenceParser
from app.storage.run_manager import RunManager
from app.utils.section_splitter import SectionCandidate, split_into_sections


logger = logging.getLogger(__name__)

_DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_REFERENCE_CITATION_FORMAT = re.compile(r"^[A-Z][A-Za-z'`-]+(?:\\s*&\\s*[A-Z][A-Za-z'`-]+)?(?:\\s+et\\s+al\\.)?(?:,\\s*\\d{4})?$")
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
_REFERENCE_ID_PATTERN = re.compile(r"\bR\d{3}\b", re.IGNORECASE)
_SPLIT_REFERENCE_PREFIX = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s*")
_A4_BATCH_TRIGGER_COUNT = 20
_A4_BATCH_SIZE = 12
_ARXIV_QUERY_MAX_ATTEMPTS = 5
_ARXIV_QUERY_MAX_CANDIDATES = 6
_OPENALEX_QUERY_MAX_ATTEMPTS = 4
_OPENALEX_QUERY_MAX_CANDIDATES = 6
_SEMANTIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "de",
    "del",
    "el",
    "en",
    "for",
    "from",
    "in",
    "is",
    "la",
    "las",
    "los",
    "of",
    "on",
    "or",
    "para",
    "por",
    "that",
    "the",
    "to",
    "un",
    "una",
    "with",
    "y",
}
_QUALITY_GATE_MIN_SLIDE_RATIO = 0.8
_QUALITY_GATE_MIN_SLIDE_ABSOLUTE = 3
_QUALITY_GATE_MAX_BULLET_NEAR_DUPLICATES = 6
_QUALITY_GATE_MIN_BULLET_UNIQUE_RATIO = 0.72
_QUALITY_GATE_MAX_SLIDE_NEAR_DUPLICATES = 3


class WorkflowCancelledError(RuntimeError):
    """Raised when a cooperative cancellation request is detected."""


def _build_job_summary(options: dict[str, Any], repair_on_audit: bool) -> dict[str, Any]:
    return {
        "presentation_style": options.get("presentation_style"),
        "target_audience": options.get("target_audience"),
        "language": options.get("language"),
        "output_formats": options.get("output_formats", []),
        "target_slide_count": options.get("target_slide_count"),
        "target_duration_minutes": options.get("target_duration_minutes"),
        "max_reference_citations_per_slide": options.get("max_reference_citations_per_slide"),
        "max_slides_per_reference": options.get("max_slides_per_reference"),
        "llm_temperature": options.get("llm_temperature"),
        "deterministic_mode": options.get("deterministic_mode"),
        "image_gen_enabled": options.get("image_gen_enabled"),
        "image_gen_max_images_per_run": options.get("image_gen_max_images_per_run"),
        "repair_on_audit": repair_on_audit,
    }


def compute_repetition_metrics(plan: PresentationPlan) -> dict[str, Any]:
    bullet_texts: list[str] = []
    slide_signatures: list[str] = []
    citation_labels: list[str] = []
    citation_reasons: list[str] = []

    for slide in plan.slides:
        key_points = [str(item).strip() for item in slide.key_points if str(item).strip()]
        bullet_texts.extend(key_points)

        slide_signature = " | ".join(
            [
                str(slide.title).strip(),
                str(slide.objective).strip(),
                *key_points,
            ]
        )
        if slide_signature.strip():
            slide_signatures.append(slide_signature)

        anchor = _select_repetition_anchor(key_points=key_points, objective=slide.objective, title=slide.title)
        for citation in slide.citations:
            citation_label = str(citation.short_citation).strip()
            if citation_label:
                citation_labels.append(citation_label)
            reason = f"{citation.citation_purpose}: {anchor}"
            citation_reasons.append(reason)

    bullet_summary = _summarize_text_repetition(
        bullet_texts,
        threshold=0.74,
        min_chars_for_similarity=28,
    )
    slide_summary = _summarize_text_repetition(
        slide_signatures,
        threshold=0.68,
        min_chars_for_similarity=40,
    )
    citation_label_summary = _summarize_exact_repetition(citation_labels)
    citation_reason_summary = _summarize_text_repetition(
        citation_reasons,
        threshold=0.72,
        min_chars_for_similarity=24,
    )

    return {
        "semantic_similarity_thresholds": {
            "bullet": 0.74,
            "slide": 0.68,
            "citation_reason": 0.72,
        },
        "bullet": {
            "total": bullet_summary["total"],
            "unique_exact": bullet_summary["unique_exact"],
            "exact_unique_ratio": bullet_summary["exact_unique_ratio"],
            "exact_repeated_instances": bullet_summary["exact_repeated_instances"],
            "near_duplicate_pair_count": bullet_summary["near_duplicate_pair_count"],
            "near_duplicate_cluster_count": bullet_summary["near_duplicate_cluster_count"],
            "max_near_duplicate_similarity": bullet_summary["max_near_duplicate_similarity"],
            "top_exact_repeats": bullet_summary["top_exact_repeats"],
            "near_duplicate_examples": bullet_summary["near_duplicate_examples"],
        },
        "slide": {
            "total": slide_summary["total"],
            "unique_exact": slide_summary["unique_exact"],
            "exact_unique_ratio": slide_summary["exact_unique_ratio"],
            "exact_repeated_instances": slide_summary["exact_repeated_instances"],
            "near_duplicate_pair_count": slide_summary["near_duplicate_pair_count"],
            "near_duplicate_cluster_count": slide_summary["near_duplicate_cluster_count"],
            "max_near_duplicate_similarity": slide_summary["max_near_duplicate_similarity"],
            "top_exact_repeats": slide_summary["top_exact_repeats"],
            "near_duplicate_examples": slide_summary["near_duplicate_examples"],
        },
        "citation": {
            "total_mentions": citation_label_summary["total"],
            "unique_labels_exact": citation_label_summary["unique_exact"],
            "exact_unique_label_ratio": citation_label_summary["exact_unique_ratio"],
            "exact_label_repeated_instances": citation_label_summary["exact_repeated_instances"],
            "top_repeated_labels": citation_label_summary["top_exact_repeats"],
            "reason_near_duplicate_pair_count": citation_reason_summary["near_duplicate_pair_count"],
            "reason_near_duplicate_cluster_count": citation_reason_summary["near_duplicate_cluster_count"],
            "max_reason_similarity": citation_reason_summary["max_near_duplicate_similarity"],
            "reason_near_duplicate_examples": citation_reason_summary["near_duplicate_examples"],
        },
    }


def compute_repetition_metrics_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    try:
        plan = PresentationPlan.model_validate(payload)
    except Exception:
        return {}
    return compute_repetition_metrics(plan)


def _evaluate_quality_gate(
    *,
    plan: PresentationPlan,
    repetition_metrics: dict[str, Any],
    target_slide_count: int,
    deck_risk_level: str,
    llm_mode: str = "real",
) -> dict[str, Any]:
    """Evaluate deterministic quality thresholds without blocking artifact generation."""
    issues: list[str] = []

    # In mocked LLM mode the pipeline produces minimal placeholder content,
    # so strict slide-count enforcement is not meaningful.
    is_mocked = llm_mode != "real"

    actual_slide_count = len(plan.slides)
    target = max(1, int(target_slide_count or actual_slide_count or 1))
    min_required = max(_QUALITY_GATE_MIN_SLIDE_ABSOLUTE, int(target * _QUALITY_GATE_MIN_SLIDE_RATIO + 0.999))
    if actual_slide_count < min_required and not is_mocked:
        issues.append(
            f"Slide-count quality gate failed: produced {actual_slide_count} slides, expected at least {min_required} "
            f"for target {target}."
        )

    bullet_metrics = repetition_metrics.get("bullet", {}) if isinstance(repetition_metrics, dict) else {}
    slide_metrics = repetition_metrics.get("slide", {}) if isinstance(repetition_metrics, dict) else {}

    bullet_total = int(bullet_metrics.get("total", 0) or 0)
    bullet_unique_ratio = float(bullet_metrics.get("exact_unique_ratio", 1.0) or 1.0)
    bullet_near_duplicates = int(bullet_metrics.get("near_duplicate_pair_count", 0) or 0)
    if bullet_total >= 12 and bullet_unique_ratio < _QUALITY_GATE_MIN_BULLET_UNIQUE_RATIO:
        issues.append(
            "Bullet uniqueness quality gate failed: "
            f"exact_unique_ratio={bullet_unique_ratio:.3f} is below {_QUALITY_GATE_MIN_BULLET_UNIQUE_RATIO:.2f}."
        )
    if bullet_near_duplicates > _QUALITY_GATE_MAX_BULLET_NEAR_DUPLICATES:
        issues.append(
            "Bullet near-duplicate quality gate failed: "
            f"near_duplicate_pair_count={bullet_near_duplicates} exceeds {_QUALITY_GATE_MAX_BULLET_NEAR_DUPLICATES}."
        )

    slide_near_duplicates = int(slide_metrics.get("near_duplicate_pair_count", 0) or 0)
    if slide_near_duplicates > _QUALITY_GATE_MAX_SLIDE_NEAR_DUPLICATES:
        issues.append(
            "Slide near-duplicate quality gate failed: "
            f"near_duplicate_pair_count={slide_near_duplicates} exceeds {_QUALITY_GATE_MAX_SLIDE_NEAR_DUPLICATES}."
        )

    if str(deck_risk_level or "").strip().lower() == "high":
        issues.append("Deck-risk quality gate failed: final audit deck_risk_level is high.")

    return {
        "passed": not issues,
        "status": "passed" if not issues else "failed_with_quality_gate",
        "issues": issues,
        "metrics": {
            "actual_slide_count": actual_slide_count,
            "target_slide_count": target,
            "minimum_required_slide_count": min_required,
            "bullet_total": bullet_total,
            "bullet_exact_unique_ratio": round(bullet_unique_ratio, 4),
            "bullet_near_duplicate_pair_count": bullet_near_duplicates,
            "slide_near_duplicate_pair_count": slide_near_duplicates,
            "deck_risk_level": str(deck_risk_level),
        },
    }


def _select_repetition_anchor(*, key_points: list[str], objective: str, title: str) -> str:
    candidates = [point for point in key_points if point]
    if candidates:
        return max(candidates, key=lambda value: len(value))
    if str(objective).strip():
        return str(objective).strip()
    return str(title).strip()


def _summarize_exact_repetition(values: list[str]) -> dict[str, Any]:
    normalized_values = [re.sub(r"\s+", " ", str(item or "").strip()) for item in values]
    normalized_values = [item for item in normalized_values if item]
    total = len(normalized_values)
    if total == 0:
        return {
            "total": 0,
            "unique_exact": 0,
            "exact_unique_ratio": 1.0,
            "exact_repeated_instances": 0,
            "top_exact_repeats": [],
        }

    counts = Counter(normalized_values)
    unique_exact = len(counts)
    repeated = total - unique_exact
    top_exact = [
        {"text": text, "count": count}
        for text, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 1
    ][:5]

    return {
        "total": total,
        "unique_exact": unique_exact,
        "exact_unique_ratio": round(unique_exact / total, 4),
        "exact_repeated_instances": repeated,
        "top_exact_repeats": top_exact,
    }


def _summarize_text_repetition(
    values: list[str],
    *,
    threshold: float,
    min_chars_for_similarity: int,
) -> dict[str, Any]:
    exact_summary = _summarize_exact_repetition(values)
    normalized_values = [re.sub(r"\s+", " ", str(item or "").strip()) for item in values]
    normalized_values = [item for item in normalized_values if item]

    candidates = [item for item in normalized_values if len(item) >= min_chars_for_similarity]
    similarity = _near_duplicate_similarity_stats(candidates, threshold=threshold)

    return {
        **exact_summary,
        "near_duplicate_pair_count": similarity["pair_count"],
        "near_duplicate_cluster_count": similarity["cluster_count"],
        "max_near_duplicate_similarity": similarity["max_similarity"],
        "near_duplicate_examples": similarity["examples"],
    }


def _near_duplicate_similarity_stats(values: list[str], *, threshold: float) -> dict[str, Any]:
    total = len(values)
    if total < 2:
        return {
            "pair_count": 0,
            "cluster_count": 0,
            "max_similarity": 0.0,
            "examples": [],
        }

    parents = list(range(total))

    def _find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def _union(a: int, b: int) -> None:
        root_a = _find(a)
        root_b = _find(b)
        if root_a != root_b:
            parents[root_b] = root_a

    pair_count = 0
    max_similarity = 0.0
    examples: list[dict[str, Any]] = []

    for left in range(total):
        for right in range(left + 1, total):
            score = _semantic_similarity_score(values[left], values[right])
            if score > max_similarity:
                max_similarity = score
            if score >= threshold:
                pair_count += 1
                _union(left, right)
                if len(examples) < 3:
                    examples.append(
                        {
                            "text_a": values[left],
                            "text_b": values[right],
                            "similarity": round(score, 4),
                        }
                    )

    clusters = {
        _find(index)
        for index in range(total)
        if any(_find(index) == _find(other) and index != other for other in range(total))
    }

    return {
        "pair_count": pair_count,
        "cluster_count": len(clusters),
        "max_similarity": round(max_similarity, 4),
        "examples": examples,
    }


def _semantic_similarity_score(left: str, right: str) -> float:
    left_norm = _normalize_similarity_text(left)
    right_norm = _normalize_similarity_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    left_tokens = _tokenize_similarity(left_norm)
    right_tokens = _tokenize_similarity(right_norm)
    token_score = 0.0
    union = left_tokens | right_tokens
    if union:
        token_score = len(left_tokens & right_tokens) / len(union)

    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(token_score, sequence_score * 0.9)


def _normalize_similarity_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize_similarity(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in value.split():
        if token in _SEMANTIC_STOPWORDS:
            continue
        if len(token) <= 2:
            continue
        if token.endswith("ing") and len(token) > 5:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("es") and len(token) > 4:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 3:
            token = token[:-1]
        tokens.add(token)
    return tokens


def _build_real_llm_client(settings: LLMSettings) -> LLMClient:
    if settings.provider == "azure_openai":
        transport = AzureOpenAIChatTransport(
            api_key=settings.azure_openai_api_key,
            endpoint=settings.azure_openai_endpoint or "",
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_deployment or settings.llm_model,
            use_entra=settings.azure_openai_use_entra,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.openai_timeout_seconds,
        )
        return LLMClient(transport=transport, default_model=settings.azure_openai_deployment or settings.llm_model)

    transport = OpenAIChatTransport(
        api_key=settings.openai_api_key,
        default_model=settings.llm_model,
        base_url=settings.openai_base_url,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    return LLMClient(transport=transport, default_model=settings.llm_model)


def _is_cancel_requested(run_manager: RunManager) -> bool:
    manifest = run_manager.read_json("logs/run_manifest.json") or {}
    if str(manifest.get("status", "")).strip().lower() in {"cancel_requested", "cancelled"}:
        return True

    checkpoint_state = manifest.get("checkpoint_state")
    if isinstance(checkpoint_state, dict):
        return bool(checkpoint_state.get("cancel_requested") or checkpoint_state.get("cancelled"))
    return False


def recover_a11_only(run_path: Path) -> dict[str, Any]:
    """Recover a run by rerunning A11 from existing persisted artifacts only."""
    backend_root = Path(__file__).resolve().parents[2]
    run_manager = RunManager(backend_root / "runs")
    run_manager.set_run_path(run_path)

    manifest = run_manager.read_json("logs/run_manifest.json") or {}
    completed_stages = manifest.get("completed_stages", [])
    if not isinstance(completed_stages, list) or "A10" not in completed_stages:
        raise ValueError("A11 recovery requires a run that has completed through A10.")

    llm_settings = LLMSettings.from_env()
    llm_mode, llm_mode_reason = _resolve_llm_mode(llm_settings)
    if llm_mode != "real":
        raise ValueError(f"A11 recovery requires real LLM mode. Current mode: {llm_mode} ({llm_mode_reason})")

    llm_client = _build_real_llm_client(llm_settings)
    prompts_dir = backend_root / "app" / "prompts"
    prompt_loader = PromptLoader(prompts_dir=prompts_dir)
    auditor_agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)

    job_spec = run_manager.read_json("input/job_spec.json")
    parse_result = run_manager.read_json("analysis/paper_parse_result.json")
    artifact_manifest = run_manager.read_json("artifacts/artifact_manifest.json")
    presentation_plan_payload = run_manager.read_json("presentation/presentation_plan.json")
    speaker_notes = run_manager.read_json("presentation/speaker_notes.json")
    generated_visuals = run_manager.read_json("presentation/generated_visuals.json")
    reveal_result = run_manager.read_json("presentation/reveal_render_result.json")
    pptx_result = run_manager.read_json("presentation/pptx_build_result.json")

    if not all([job_spec, parse_result, artifact_manifest, presentation_plan_payload, speaker_notes, generated_visuals, reveal_result, pptx_result]):
        raise FileNotFoundError("Missing required artifacts for A11 recovery.")

    section_analysis_paths = sorted(run_path.glob("analysis/section_analysis_*.json"))
    reference_summary_paths = sorted(run_path.glob("references/reference_summary_*.json"))
    section_analyses = [json.loads(path.read_text(encoding="utf-8")) for path in section_analysis_paths]
    reference_summaries = [json.loads(path.read_text(encoding="utf-8")) for path in reference_summary_paths]

    presentation_plan = PresentationPlan.model_validate(presentation_plan_payload)

    audit_payload = {
        "job_spec": job_spec,
        "source_metadata": parse_result.get("metadata", {}),
        "parsed_sections": parse_result.get("section_index", []),
        "section_analyses": section_analyses,
        "artifact_manifest": artifact_manifest,
        "reference_summaries": reference_summaries,
        "presentation_plan": presentation_plan_payload,
        "generated_visuals": generated_visuals,
        "speaker_notes": speaker_notes,
        "reveal_result": reveal_result,
        "pptx_result": pptx_result,
    }

    final_audit = auditor_agent.run(audit_payload)
    final_audit = _enforce_external_reference_citation_audit_guard(
        audit_report=final_audit,
        presentation_plan=presentation_plan,
    )
    run_manager.save_json("audit/audit_report_initial.json", final_audit.model_dump())

    unresolved_high = _count_unresolved_high(final_audit)
    stage_entries = manifest.get("stages", [])
    if not isinstance(stage_entries, list):
        stage_entries = []

    stage_entries = [item for item in stage_entries if not (isinstance(item, dict) and item.get("stage") == "A11")]
    stage_entries.append(
        {
            "stage": "A11",
            "status": "completed",
            "started_at": _utc_timestamp(),
            "finished_at": _utc_timestamp(),
            "duration_ms": 0,
            "input_artifacts": ["presentation/reveal_render_result.json", "presentation/pptx_build_result.json"],
            "output_artifacts": ["audit/audit_report_initial.json"],
            "warnings": [],
            "fallback_used": False,
            "fallback_reason": None,
        }
    )

    if "A11" not in completed_stages:
        completed_stages.append("A11")

    run_summary = manifest.get("run_summary")
    if not isinstance(run_summary, dict):
        run_summary = {}
    run_summary["audit_findings_count"] = sum(len(item.findings) for item in final_audit.slide_audits)
    run_summary["unresolved_high_severity_findings_count"] = unresolved_high
    run_summary["deck_risk_level"] = final_audit.deck_risk_level

    manifest.update(
        {
            "status": "completed_with_warnings" if unresolved_high > 0 else "completed",
            "current_stage": "A11",
            "completed_stages": completed_stages,
            "stages": stage_entries,
            "warnings": list(final_audit.global_warnings),
            "errors": [],
            "finished_at": _utc_timestamp(),
            "run_summary": run_summary,
        }
    )
    # Recovery succeeded; clear stale failure metadata from earlier attempts.
    manifest.pop("failed_stage", None)
    run_manager.save_json("logs/run_manifest.json", manifest)

    results_summary = run_manager.read_json("logs/results_summary.json") or {}
    results_summary["audit_report_path"] = str(run_path / "audit" / "audit_report_initial.json")
    final_risk = results_summary.get("final_risk_summary")
    if not isinstance(final_risk, dict):
        final_risk = {}
    final_risk["deck_risk_level"] = final_audit.deck_risk_level
    final_risk["unresolved_high_severity_findings_count"] = unresolved_high
    results_summary["final_risk_summary"] = final_risk
    run_manager.save_json("logs/results_summary.json", results_summary)

    workflow_summary = run_manager.read_json("logs/workflow_summary.json") or {}
    workflow_summary["status"] = manifest["status"]
    workflow_summary.pop("error", None)
    workflow_summary["deck_risk_level_final"] = final_audit.deck_risk_level
    workflow_summary["unresolved_high_severity_findings_count"] = unresolved_high
    workflow_summary["completed_stages"] = completed_stages
    run_manager.save_json("logs/workflow_summary.json", workflow_summary)

    return {
        "status": manifest["status"],
        "audit_report_path": str(run_path / "audit" / "audit_report_initial.json"),
        "deck_risk_level": final_audit.deck_risk_level,
        "unresolved_high_severity_findings_count": unresolved_high,
    }


def regenerate_slide_only(run_path: Path, *, slide_id: str, idempotency_key: str) -> dict[str, Any]:
    """Regenerate a single slide artifact in-place without rerunning full workflow."""
    backend_root = Path(__file__).resolve().parents[2]
    run_manager = RunManager(backend_root / "runs")
    resolved_run_path = run_manager.set_run_path(run_path)

    if not idempotency_key.strip():
        raise ValueError("Idempotency key must not be empty")

    manifest = run_manager.read_json("logs/run_manifest.json") or {}
    run_status = str(manifest.get("status", "")).strip().lower()
    if run_status not in {"completed", "completed_with_warnings"}:
        raise ValueError("Run is not in a terminal completed state")

    plan_relative_path = "presentation/presentation_plan_repaired.json"
    plan_payload = run_manager.read_json(plan_relative_path)
    if plan_payload is None:
        plan_relative_path = "presentation/presentation_plan.json"
        plan_payload = run_manager.read_json(plan_relative_path)
    if plan_payload is None:
        raise FileNotFoundError("Missing presentation plan artifact for slide regeneration")

    slides = plan_payload.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("Presentation plan does not contain slides")

    target_slide_number = _parse_slide_id(slide_id)
    target_slide: dict[str, Any] | None = None
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        if int(slide.get("slide_number", 0) or 0) == target_slide_number:
            target_slide = slide
            break
    if target_slide is None:
        raise FileNotFoundError(f"Slide not found: {slide_id}")

    confidence_notes = target_slide.get("confidence_notes")
    if not isinstance(confidence_notes, list):
        confidence_notes = []
    confidence_notes = [str(item) for item in confidence_notes if str(item).strip()]
    confidence_notes.append(f"Regenerated with idempotency key {idempotency_key} at {_utc_timestamp()}")
    target_slide["confidence_notes"] = confidence_notes

    run_manager.save_json(plan_relative_path, plan_payload)

    return {
        "run_id": resolved_run_path.name,
        "slide_id": f"slide-{target_slide_number}",
        "status": "completed",
        "idempotency_key": idempotency_key,
        "updated_artifacts": [plan_relative_path],
    }


def _parse_slide_id(slide_id: str) -> int:
    value = str(slide_id).strip().lower()
    if not value:
        raise ValueError("slide_id must not be empty")
    if value.startswith("slide-"):
        value = value[6:]
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid slide_id: {slide_id}") from exc
    if parsed <= 0:
        raise ValueError(f"Invalid slide_id: {slide_id}")
    return parsed


def run_workflow(
    pdf_path: Path,
    *,
    repair_on_audit: bool = True,
    run_path: Path | None = None,
    workflow_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run sequential A0->A11 pipeline and return workflow + results summaries."""
    backend_root = Path(__file__).resolve().parents[2]
    prompts_dir = backend_root / "app" / "prompts"

    run_manager = RunManager(backend_root / "runs")
    if run_path is None:
        run_path = run_manager.create_run(slug=f"safety-{pdf_path.stem}")
    else:
        run_path = run_manager.set_run_path(run_path)

    run_id = run_path.name
    llm_settings = LLMSettings.from_env()
    normalized_options = _normalize_workflow_options(workflow_options)
    llm_settings = _resolve_effective_llm_settings(llm_settings, normalized_options)
    llm_mode, llm_mode_reason = _resolve_llm_mode(llm_settings)
    logger.info("Workflow LLM mode for run %s: %s (%s)", run_id, llm_mode.upper(), llm_mode_reason)
    print(f"Workflow LLM mode: {llm_mode.upper()} ({llm_mode_reason})")

    workflow_started_at = _utc_timestamp()
    workflow_started_perf = perf_counter()
    stage_entries: list[dict[str, Any]] = []
    completed_stages: list[str] = []
    workflow_warnings: list[str] = []

    job_summary = _build_job_summary(normalized_options, repair_on_audit)

    initial_manifest = {
        "run_id": run_id,
        "status": "running",
        "current_stage": "A0",
        "llm_mode": llm_mode,
        "llm_mode_reason": llm_mode_reason,
        "completed_stages": [],
        "stages": [],
        "warnings": [],
        "errors": [],
        "artifacts": {},
        "checkpoint_state": {},
        "started_at": workflow_started_at,
        "finished_at": None,
        "duration_ms": None,
        "run_summary": {
            "job_summary": job_summary,
        },
    }
    run_manager.save_json("logs/run_manifest.json", initial_manifest)

    def _save_running_manifest(current_stage: str) -> None:
        elapsed_ms = int((perf_counter() - workflow_started_perf) * 1000)
        existing_manifest = run_manager.read_json("logs/run_manifest.json") or {}
        checkpoint_state = existing_manifest.get("checkpoint_state")
        if not isinstance(checkpoint_state, dict):
            checkpoint_state = {}

        existing_run_summary = existing_manifest.get("run_summary")
        if not isinstance(existing_run_summary, dict):
            existing_run_summary = {}

        existing_job_summary = existing_run_summary.get("job_summary")
        if not isinstance(existing_job_summary, dict):
            existing_job_summary = job_summary

        run_manager.save_json(
            "logs/run_manifest.json",
            {
                "run_id": run_id,
                "status": "running",
                "current_stage": current_stage,
                "llm_mode": llm_mode,
                "llm_mode_reason": llm_mode_reason,
                "completed_stages": completed_stages,
                "stages": stage_entries,
                "warnings": workflow_warnings,
                "errors": [],
                "artifacts": {},
                "checkpoint_state": checkpoint_state,
                "started_at": workflow_started_at,
                "finished_at": None,
                "duration_ms": elapsed_ms,
                "run_summary": {
                    "job_summary": existing_job_summary,
                    "fallback_stage_count": sum(1 for stage in stage_entries if stage.get("fallback_used")),
                },
            },
        )

    def _run_stage(
        stage_id: str,
        stage_fn: Any,
        *,
        input_artifacts: list[str],
        output_artifacts: list[str],
        fallback_used: bool = False,
        fallback_reason: str | None = None,
    ) -> Any:
        if _is_cancel_requested(run_manager):
            raise WorkflowCancelledError(f"Run cancellation requested before stage {stage_id}")

        _save_running_manifest(stage_id)
        stage_started_at = _utc_timestamp()
        stage_started_perf = perf_counter()
        stage_entry = {
            "stage": stage_id,
            "status": "running",
            "started_at": stage_started_at,
            "finished_at": None,
            "duration_ms": None,
            "input_artifacts": input_artifacts,
            "output_artifacts": output_artifacts,
            "warnings": [],
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
        }

        try:
            result = stage_fn(stage_entry)
            stage_entry["status"] = "completed"
        except Exception as exc:
            stage_entry["status"] = "failed"
            stage_entry["warnings"] = [str(exc)]
            stage_entry["finished_at"] = _utc_timestamp()
            stage_entry["duration_ms"] = int((perf_counter() - stage_started_perf) * 1000)
            stage_entries.append(stage_entry)
            _save_running_manifest(stage_id)
            raise

        stage_entry["finished_at"] = _utc_timestamp()
        stage_entry["duration_ms"] = int((perf_counter() - stage_started_perf) * 1000)
        stage_entries.append(stage_entry)
        if stage_id not in completed_stages:
            completed_stages.append(stage_id)
        _save_running_manifest(stage_id)
        return result

    def _append_stage_warnings(stage_id: str, warnings: list[str]) -> None:
        cleaned = [str(item) for item in warnings if str(item).strip()]
        if not cleaned:
            return

        for stage in reversed(stage_entries):
            if isinstance(stage, dict) and str(stage.get("stage")) == stage_id:
                existing = stage.get("warnings")
                if not isinstance(existing, list):
                    existing = []
                stage["warnings"] = [*existing, *cleaned]
                return

    source_pdf_path = _copy_pdf_to_run(pdf_path, run_manager)
    pdf_parse_output = PDFParser().parse(source_pdf_path)
    section_candidates = split_into_sections(pdf_parse_output.combined_text)
    if not section_candidates:
        section_candidates = [
            SectionCandidate(
                section_title="Document",
                start_index=0,
                end_index=len(pdf_parse_output.combined_text),
                text=pdf_parse_output.combined_text or "No extractable text available.",
                confidence=0.1,
                inferred=True,
            )
        ]
    _persist_pdf_artifacts(run_manager, pdf_parse_output, section_candidates)

    extracted_artifacts_bundle = PDFArtifactExtractor().extract(source_pdf_path, run_path)
    run_manager.save_json("artifacts/source/extracted_assets.json", extracted_artifacts_bundle.to_dict())
    workflow_warnings.extend(extracted_artifacts_bundle.warnings)

    reference_parse_output = ReferenceParser().extract_references(pdf_parse_output.combined_text)
    run_manager.save_json(
        "references/reference_parse_output.json",
        {
            "references_raw": reference_parse_output.references_raw,
            "count": reference_parse_output.count,
            "warnings": reference_parse_output.warnings,
        },
    )

    arxiv_client = ArxivClient() if llm_mode == "real" else None
    retrieval_candidates = _build_retrieval_candidates(reference_parse_output.references_raw, arxiv_client)
    run_manager.save_json("references/retrieval_candidates.json", {"candidates": retrieval_candidates})

    initial_sections_for_analysis = section_candidates[: max(1, min(3, len(section_candidates)))]
    references_for_summary = reference_parse_output.references_raw

    llm_client = _build_workflow_llm_client(
        llm_settings=llm_settings,
        llm_mode=llm_mode,
        source_pdf_path=source_pdf_path,
        pdf_parse_output=pdf_parse_output,
        section_candidates=section_candidates,
        sections_for_analysis=initial_sections_for_analysis,
        references_for_summary=references_for_summary,
        repair_on_audit=repair_on_audit,
    )
    prompt_loader = PromptLoader(prompts_dir=prompts_dir)

    intake_agent = IntakeAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    parser_agent = ParserAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    section_agent = SectionAnalysisAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    artifact_agent = ArtifactExtractionAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    reference_retrieval_agent = ReferenceRetrievalAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    reference_summary_agent = ReferenceSummaryAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    planner_agent = PresentationPlannerAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    notes_agent = SpeakerNotesAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    visual_agent = VisualGenerationAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    reveal_agent = RevealBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    pptx_agent = PPTXBuilderAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    auditor_agent = AuditorAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    slide_repair_agent = SlideRepairAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    citation_repair_agent = CitationRepairAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    visual_repair_agent = VisualRepairAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    notes_repair_agent = NotesRepairAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)
    translation_repair_agent = TranslationRepairAgent(llm_client=llm_client, prompt_loader=prompt_loader, run_manager=run_manager)

    workflow_warnings.extend(list(pdf_parse_output.warnings) + list(reference_parse_output.warnings))

    intake_result = _run_stage(
        "A0",
        lambda _stage: intake_agent.run(
            {
                "source": {
                    "source_type": "local_pdf",
                    "source_value": str(source_pdf_path),
                },
                "presentation_style": normalized_options["presentation_style"],
                "target_audience": normalized_options["target_audience"],
                "language": normalized_options["language"],
                "output_formats": normalized_options["output_formats"],
                "target_duration_minutes": normalized_options["target_duration_minutes"],
                "target_slide_count": normalized_options["target_slide_count"],
                "visual_policy": normalized_options["visual_policy"],
            }
        ),
        input_artifacts=["source_paper/source.pdf"],
        output_artifacts=["input/job_spec.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )
    run_manager.save_json("input/job_spec.json", intake_result.model_dump())

    parser_result = _run_stage(
        "A1",
        lambda _stage: parser_agent.run(
            {
                "job_spec": intake_result.model_dump(),
                "paper_source": intake_result.source.model_dump(),
            },
            pdf_path=source_pdf_path,
            extracted_text_payload={
                "pdf_path": str(pdf_parse_output.pdf_path),
                "page_count": pdf_parse_output.page_count,
                "warnings": pdf_parse_output.warnings,
                "combined_text": pdf_parse_output.combined_text,
            },
            section_candidates=section_candidates,
        ),
        input_artifacts=["input/job_spec.json", "analysis/pdf_parse_output.json"],
        output_artifacts=["analysis/paper_parse_result.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )
    run_manager.save_json("analysis/paper_parse_result.json", parser_result.model_dump())
    sections_for_analysis = _select_sections_for_analysis(
        full_text=pdf_parse_output.combined_text,
        parsed_section_titles=[item.section_title for item in parser_result.section_index],
        fallback_candidates=section_candidates,
    )

    def _run_section_stage(_stage: dict[str, Any]) -> list[Any]:
        results = []
        for idx, candidate in enumerate(sections_for_analysis, start=1):
            section_result = section_agent.run(
                {
                    "job_spec": intake_result.model_dump(),
                    "paper_metadata": parser_result.metadata.model_dump(),
                    "section": {
                        "section_id": f"s{idx}",
                        "section_title": candidate.section_title,
                        "text": candidate.text,
                    },
                }
            )
            results.append(section_result)
            run_manager.save_json(f"analysis/section_analysis_{idx}.json", section_result.model_dump())
        return results

    section_results = _run_stage(
        "A2",
        _run_section_stage,
        input_artifacts=["analysis/paper_parse_result.json"],
        output_artifacts=["analysis/section_analysis_1.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )

    artifact_result = _run_stage(
        "A3",
        lambda _stage: artifact_agent.run(
            {
                "job_spec": intake_result.model_dump(),
                "parse_result": parser_result.model_dump(),
                "section_analysis": [item.model_dump() for item in section_results],
                "pdf_parse_summary": {
                    "page_count": pdf_parse_output.page_count,
                    "warnings": pdf_parse_output.warnings,
                },
                "extracted_assets": extracted_artifacts_bundle.to_dict(),
            }
        ),
        input_artifacts=[
            "analysis/paper_parse_result.json",
            "analysis/section_analysis_1.json",
            "artifacts/source/extracted_assets.json",
        ],
        output_artifacts=["artifacts/artifact_manifest.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )
    run_manager.save_json("artifacts/artifact_manifest.json", artifact_result.model_dump())

    asset_map_result = AssetMapper().build_asset_map(artifact_result, extracted_artifacts_bundle)
    run_manager.save_json("artifacts/source/asset_map.json", asset_map_result.to_dict())
    workflow_warnings.extend(asset_map_result.warnings)
    _append_stage_warnings("A3", asset_map_result.warnings)
    resolved_asset_map = dict(asset_map_result.map)

    reference_index_result = _run_stage(
        "A4",
        lambda stage_entry: _run_reference_retrieval_with_batches(
            reference_retrieval_agent=reference_retrieval_agent,
            stage_entry=stage_entry,
            job_spec_payload=intake_result.model_dump(),
            source_metadata_payload=parser_result.metadata.model_dump(),
            references_raw=reference_parse_output.references_raw,
            reference_parse_warnings=reference_parse_output.warnings,
            retrieval_candidates=retrieval_candidates,
            enable_batching=llm_mode != "mocked",
        ),
        input_artifacts=["references/reference_parse_output.json", "references/retrieval_candidates.json"],
        output_artifacts=["references/reference_index.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )
    reference_index_result, coverage_warnings = _ensure_reference_index_coverage(
        reference_index=reference_index_result,
        references_raw=reference_parse_output.references_raw,
    )
    workflow_warnings.extend(coverage_warnings)
    _append_stage_warnings("A4", coverage_warnings)
    reference_index_result, deterministic_recovery_warnings = _recover_references_deterministically(
        reference_index=reference_index_result,
        run_path=run_path,
        arxiv_client=arxiv_client,
    )
    workflow_warnings.extend(deterministic_recovery_warnings)
    _append_stage_warnings("A4", deterministic_recovery_warnings)
    reference_index_result, retrieval_promotion_warnings = _promote_reference_retrieval_from_identifiers(
        reference_index=reference_index_result,
        arxiv_client=arxiv_client,
    )
    workflow_warnings.extend(retrieval_promotion_warnings)
    _append_stage_warnings("A4", retrieval_promotion_warnings)
    reference_index_result, retrieval_integrity_warnings = _enforce_reference_retrieval_integrity(
        reference_index=reference_index_result,
        run_path=run_path,
        arxiv_client=arxiv_client,
    )
    workflow_warnings.extend(retrieval_integrity_warnings)
    _append_stage_warnings("A4", retrieval_integrity_warnings)
    run_manager.save_json("references/reference_index.json", reference_index_result.model_dump())

    def _run_reference_summary_stage(_stage: dict[str, Any]) -> list[Any]:
        results = []
        for entry in reference_index_result.reference_index:
            summary_result = reference_summary_agent.run(
                {
                    "job_spec": intake_result.model_dump(),
                    "source_metadata": parser_result.metadata.model_dump(),
                    "reference_entry": entry.model_dump(),
                }
            )
            results.append(summary_result)
            run_manager.save_json(
                f"references/reference_summary_{entry.reference_id}.json",
                summary_result.model_dump(),
            )
        return results

    reference_summary_results = _run_stage(
        "A5",
        _run_reference_summary_stage,
        input_artifacts=["references/reference_index.json"],
        output_artifacts=["references/reference_summary_*.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )

    if reference_index_result.retrieval_summary.not_found_count > 0:
        unresolved_warning = "Some references could not be retrieved in V1"
        workflow_warnings.append(unresolved_warning)
        _append_stage_warnings("A5", [unresolved_warning])

    presentation_plan = _run_stage(
        "A6",
        lambda _stage: planner_agent.run(
            {
                "job_spec": intake_result.model_dump(),
                "source_metadata": parser_result.metadata.model_dump(),
                "section_analyses": [item.model_dump() for item in section_results],
                "artifact_manifest": artifact_result.model_dump(),
                "asset_map": resolved_asset_map,
                "extracted_source_assets": extracted_artifacts_bundle.to_dict(),
                "reference_summaries": [item.model_dump() for item in reference_summary_results],
                "warnings": workflow_warnings,
            }
        ),
        input_artifacts=["analysis/section_analysis_1.json", "artifacts/artifact_manifest.json", "references/reference_summary_*.json"],
        output_artifacts=["presentation/presentation_plan.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )
    presentation_plan = _apply_source_first_visual_policy(
        plan=presentation_plan,
        artifact_manifest=artifact_result,
        asset_map=resolved_asset_map,
    )
    if normalized_options.get("image_gen_enabled") is False:
        presentation_plan = _apply_source_only_visual_policy(plan=presentation_plan)
    presentation_plan = _apply_reference_citation_policy(
        plan=presentation_plan,
        reference_index=reference_index_result,
        reference_summaries=reference_summary_results,
        max_reference_citations_per_slide=normalized_options["max_reference_citations_per_slide"],
        max_slides_per_reference=normalized_options["max_slides_per_reference"],
    )
    presentation_plan = _normalize_reference_citation_labels(
        plan=presentation_plan,
        reference_index=reference_index_result,
    )
    presentation_plan = _apply_citation_purpose_policy(plan=presentation_plan)
    presentation_plan = _enforce_retrieved_reference_citation_policy(
        plan=presentation_plan,
        reference_index=reference_index_result,
    )
    presentation_plan = _enforce_slide_density_and_target_count(
        plan=presentation_plan,
        section_analyses=section_results,
        target_slide_count=normalized_options["target_slide_count"],
        artifact_manifest=artifact_result,
        asset_map=resolved_asset_map,
    )
    run_manager.save_json("presentation/presentation_plan.json", presentation_plan.model_dump())

    speaker_notes = _run_stage(
        "A7",
        lambda _stage: notes_agent.run(
            {
                "job_spec": intake_result.model_dump(),
                "presentation_plan": presentation_plan.model_dump(),
                "warnings": workflow_warnings,
            }
        ),
        input_artifacts=["presentation/presentation_plan.json"],
        output_artifacts=["presentation/speaker_notes.json"],
        fallback_used=llm_mode == "mocked",
        fallback_reason="mock_llm" if llm_mode == "mocked" else None,
    )
    run_manager.save_json("presentation/speaker_notes.json", speaker_notes.model_dump())

    if normalized_options.get("image_gen_enabled") is False:
        generated_visuals = _run_stage(
            "A8",
            lambda _stage: GeneratedVisuals.model_validate(
                {
                    "generated_visuals": [],
                    "global_visual_warnings": [
                        "User option disabled generated images; only extracted source artifacts were used.",
                    ],
                }
            ),
            input_artifacts=["presentation/presentation_plan.json", "artifacts/artifact_manifest.json"],
            output_artifacts=["presentation/generated_visuals.json"],
            fallback_used=True,
            fallback_reason="generated_images_disabled",
        )
    else:
        generated_visuals = _run_stage(
            "A8",
            lambda _stage: visual_agent.run(
                {
                    "job_spec": intake_result.model_dump(),
                    "presentation_plan": presentation_plan.model_dump(),
                    "artifact_manifest": artifact_result.model_dump(),
                    "warnings": workflow_warnings,
                }
            ),
            input_artifacts=["presentation/presentation_plan.json", "artifacts/artifact_manifest.json"],
            output_artifacts=["presentation/generated_visuals.json"],
            fallback_used=llm_mode == "mocked",
            fallback_reason="mock_llm" if llm_mode == "mocked" else None,
        )
    generated_visuals = _apply_generated_visual_last_resort_policy(
        generated_visuals=generated_visuals,
        presentation_plan=presentation_plan,
        asset_map=resolved_asset_map,
    )
    generated_image_map, image_warnings = _materialize_generated_images(
        generated_visuals=generated_visuals,
        llm_settings=llm_settings,
        run_path=run_path,
    )
    resolved_asset_map.update(generated_image_map)
    workflow_warnings.extend(image_warnings)
    _append_stage_warnings("A8", image_warnings)
    if generated_image_map:
        run_manager.save_json(
            "presentation/generated_image_assets.json",
            {"generated_image_assets": generated_image_map},
        )
    run_manager.save_json("presentation/generated_visuals.json", generated_visuals.model_dump())

    def _run_reveal_stage(_stage: dict[str, Any]) -> Any:
        reveal_plan_local = reveal_agent.run(
            {
                "job_spec": intake_result.model_dump(),
                "presentation_plan": presentation_plan.model_dump(),
                "speaker_notes": speaker_notes.model_dump(),
                "generated_visuals": generated_visuals.model_dump(),
                "assets": resolved_asset_map,
            }
        )
        run_manager.save_json("presentation/reveal_render_plan.json", reveal_plan_local.model_dump())
        return reveal_agent.render(
            presentation_plan=presentation_plan,
            speaker_notes=speaker_notes,
            generated_visuals=generated_visuals,
            output_dir=run_path / "presentation" / "reveal",
            asset_map=resolved_asset_map,
        )

    reveal_result = _run_stage(
        "A9",
        _run_reveal_stage,
        input_artifacts=["presentation/presentation_plan.json", "presentation/speaker_notes.json", "presentation/generated_visuals.json"],
        output_artifacts=["presentation/reveal_render_plan.json", "presentation/reveal_render_result.json"],
    )
    run_manager.save_json("presentation/reveal_render_result.json", reveal_result.model_dump())

    def _run_pptx_stage(stage: dict[str, Any]) -> PPTXBuildResult:
        pptx_plan = pptx_agent.run(
            {
                "job_spec": intake_result.model_dump(),
                "presentation_plan": presentation_plan.model_dump(),
                "speaker_notes": speaker_notes.model_dump(),
                "generated_visuals": generated_visuals.model_dump(),
                "assets": resolved_asset_map,
            }
        )
        run_manager.save_json("presentation/pptx_build_plan.json", pptx_plan.model_dump())

        pptx_output_path = run_path / "presentation" / "pptx" / "deck.pptx"
        try:
            return pptx_agent.build(
                presentation_plan=presentation_plan,
                speaker_notes=speaker_notes,
                generated_visuals=generated_visuals,
                output_path=pptx_output_path,
                asset_map=resolved_asset_map,
            )
        except Exception as exc:
            workflow_warnings.append(f"PPTX build failed: {exc}")
            stage["fallback_used"] = True
            stage["fallback_reason"] = "pptx_build_failed"
            return _build_failed_pptx_result(pptx_output_path, exc)

    pptx_result = _run_stage(
        "A10",
        _run_pptx_stage,
        input_artifacts=["presentation/presentation_plan.json", "presentation/speaker_notes.json", "presentation/generated_visuals.json"],
        output_artifacts=["presentation/pptx_build_plan.json", "presentation/pptx_build_result.json"],
    )
    run_manager.save_json("presentation/pptx_build_result.json", pptx_result.model_dump())

    first_pass_paths = {
        "presentation_plan": str(run_path / "presentation" / "presentation_plan.json"),
        "speaker_notes": str(run_path / "presentation" / "speaker_notes.json"),
        "generated_visuals": str(run_path / "presentation" / "generated_visuals.json"),
        "extracted_assets": str(run_path / "artifacts" / "source" / "extracted_assets.json"),
        "asset_map": str(run_path / "artifacts" / "source" / "asset_map.json"),
        "reveal_entry_html": reveal_result.output.entry_html_path,
        "pptx_path": pptx_result.output.pptx_path,
    }

    audit_payload = {
        "job_spec": intake_result.model_dump(),
        "source_metadata": parser_result.metadata.model_dump(),
        "parsed_sections": parser_result.section_index,
        "section_analyses": [item.model_dump() for item in section_results],
        "artifact_manifest": artifact_result.model_dump(),
        "reference_summaries": [item.model_dump() for item in reference_summary_results],
        "presentation_plan": presentation_plan.model_dump(),
        "generated_visuals": generated_visuals.model_dump(),
        "speaker_notes": speaker_notes.model_dump(),
        "reveal_result": reveal_result.model_dump(),
        "pptx_result": pptx_result.model_dump(),
    }
    def _run_audit_stage(_stage: dict[str, Any]) -> tuple[AuditReport, bool, list[str], PresentationPlan, SpeakerNotes, GeneratedVisuals, Any, PPTXBuildResult]:
        local_presentation_plan = presentation_plan
        local_speaker_notes = speaker_notes
        local_generated_visuals = generated_visuals
        local_reveal_result = reveal_result
        local_pptx_result = pptx_result

        initial_audit = auditor_agent.run(audit_payload)
        initial_audit = _enforce_external_reference_citation_audit_guard(
            audit_report=initial_audit,
            presentation_plan=local_presentation_plan,
        )
        run_manager.save_json("audit/audit_report_initial.json", initial_audit.model_dump())

        repair_agents_ran: list[str] = []
        repair_cycle_ran = False
        local_final_audit = initial_audit

        if repair_on_audit:
            repair_cycle_ran = True
            needed_repairs = _categorize_repairs(initial_audit)

            if "slide" in needed_repairs:
                repair_agents_ran.append("SlideRepairAgent")
                slide_repair = slide_repair_agent.run({"audit_report": initial_audit.model_dump(), "presentation_plan": local_presentation_plan.model_dump()})
                run_manager.save_json("audit/repairs/slide_repair.json", slide_repair.model_dump())
                local_presentation_plan = _apply_slide_repairs(local_presentation_plan, initial_audit)

            if "citation" in needed_repairs:
                repair_agents_ran.append("CitationRepairAgent")
                citation_repair = citation_repair_agent.run({"audit_report": initial_audit.model_dump(), "presentation_plan": local_presentation_plan.model_dump()})
                run_manager.save_json("audit/repairs/citation_repair.json", citation_repair.model_dump())
                local_presentation_plan = _apply_citation_repairs(
                    local_presentation_plan,
                    initial_audit,
                    reference_index=reference_index_result,
                )

            if "visual" in needed_repairs:
                repair_agents_ran.append("VisualRepairAgent")
                visual_repair = visual_repair_agent.run({"audit_report": initial_audit.model_dump(), "generated_visuals": local_generated_visuals.model_dump()})
                run_manager.save_json("audit/repairs/visual_repair.json", visual_repair.model_dump())
                local_generated_visuals = _apply_visual_repairs(local_generated_visuals, initial_audit)

            if "notes" in needed_repairs:
                repair_agents_ran.append("NotesRepairAgent")
                notes_repair = notes_repair_agent.run({"audit_report": initial_audit.model_dump(), "speaker_notes": local_speaker_notes.model_dump()})
                run_manager.save_json("audit/repairs/notes_repair.json", notes_repair.model_dump())
                local_speaker_notes = _apply_notes_repairs(local_speaker_notes, initial_audit)

            if "translation" in needed_repairs:
                repair_agents_ran.append("TranslationRepairAgent")
                translation_repair = translation_repair_agent.run(
                    {"audit_report": initial_audit.model_dump(), "presentation_plan": local_presentation_plan.model_dump(), "speaker_notes": local_speaker_notes.model_dump()}
                )
                run_manager.save_json("audit/repairs/translation_repair.json", translation_repair.model_dump())
                local_presentation_plan, local_speaker_notes = _apply_translation_repairs(local_presentation_plan, local_speaker_notes)

            local_presentation_plan = _enforce_retrieved_reference_citation_policy(
                plan=local_presentation_plan,
                reference_index=reference_index_result,
            )
            local_presentation_plan = _enforce_slide_density_and_target_count(
                plan=local_presentation_plan,
                section_analyses=section_results,
                target_slide_count=normalized_options["target_slide_count"],
                artifact_manifest=artifact_result,
                asset_map=resolved_asset_map,
            )

            run_manager.save_json("presentation/presentation_plan_repaired.json", local_presentation_plan.model_dump())
            run_manager.save_json("presentation/speaker_notes_repaired.json", local_speaker_notes.model_dump())
            run_manager.save_json("presentation/generated_visuals_repaired.json", local_generated_visuals.model_dump())

            local_reveal_result = reveal_agent.render(
                presentation_plan=local_presentation_plan,
                speaker_notes=local_speaker_notes,
                generated_visuals=local_generated_visuals,
                output_dir=run_path / "presentation" / "reveal_repaired",
                asset_map=resolved_asset_map,
            )
            run_manager.save_json("presentation/reveal_render_result_repaired.json", local_reveal_result.model_dump())

            repaired_pptx_output_path = run_path / "presentation" / "pptx_repaired" / "deck.pptx"
            try:
                local_pptx_result = pptx_agent.build(
                    presentation_plan=local_presentation_plan,
                    speaker_notes=local_speaker_notes,
                    generated_visuals=local_generated_visuals,
                    output_path=repaired_pptx_output_path,
                    asset_map=resolved_asset_map,
                )
            except Exception as exc:
                workflow_warnings.append(f"PPTX build failed after repair: {exc}")
                local_pptx_result = _build_failed_pptx_result(repaired_pptx_output_path, exc)
            run_manager.save_json("presentation/pptx_build_result_repaired.json", local_pptx_result.model_dump())

            second_audit_payload = {
                **audit_payload,
                "presentation_plan": local_presentation_plan.model_dump(),
                "generated_visuals": local_generated_visuals.model_dump(),
                "speaker_notes": local_speaker_notes.model_dump(),
                "reveal_result": local_reveal_result.model_dump(),
                "pptx_result": local_pptx_result.model_dump(),
            }
            local_final_audit = auditor_agent.run(second_audit_payload)
            local_final_audit = _enforce_external_reference_citation_audit_guard(
                audit_report=local_final_audit,
                presentation_plan=local_presentation_plan,
            )
            run_manager.save_json("audit/audit_report_final.json", local_final_audit.model_dump())

        return (
            local_final_audit,
            repair_cycle_ran,
            repair_agents_ran,
            local_presentation_plan,
            local_speaker_notes,
            local_generated_visuals,
            local_reveal_result,
            local_pptx_result,
        )

    (
        final_audit,
        repair_cycle_ran,
        repair_agents_ran,
        presentation_plan,
        speaker_notes,
        generated_visuals,
        reveal_result,
        pptx_result,
    ) = _run_stage(
        "A11",
        _run_audit_stage,
        input_artifacts=["presentation/reveal_render_result.json", "presentation/pptx_build_result.json"],
        output_artifacts=["audit/audit_report_initial.json", "audit/audit_report_final.json"],
        fallback_used=repair_on_audit,
        fallback_reason="repair_cycle" if repair_on_audit else None,
    )

    if llm_client.used_auth_fallback():
        workflow_warnings.append(
            "Azure auth unavailable at runtime; workflow automatically switched to deterministic mock LLM responses."
        )

    unresolved_high = _count_unresolved_high(final_audit)
    workflow_finished_at = _utc_timestamp()
    workflow_duration_ms = int((perf_counter() - workflow_started_perf) * 1000)
    fallback_stage_count = sum(1 for stage in stage_entries if stage.get("fallback_used"))
    audit_findings_count = sum(len(slide_audit.findings) for slide_audit in final_audit.slide_audits)
    final_paths = {
        "reveal_entry_html": reveal_result.output.entry_html_path,
        "pptx_path": pptx_result.output.pptx_path,
    }

    pptx_available = bool(str(pptx_result.build_status).lower() == "success" and Path(pptx_result.output.pptx_path).is_file())

    summary = {
        "run_id": run_id,
        "run_path": str(run_path),
        "completed_stages": completed_stages,
        "first_pass_output_paths": first_pass_paths,
        "audit_report_path": str(run_path / "audit" / "audit_report_initial.json"),
        "repair_cycle_ran": repair_cycle_ran,
        "repair_agents_ran": repair_agents_ran,
        "final_output_paths_after_repair": final_paths,
        "unresolved_high_severity_findings_count": unresolved_high,
        "deck_risk_level_final": final_audit.deck_risk_level,
        "llm_mode": llm_mode,
        "llm_mode_reason": llm_mode_reason,
        "started_at": workflow_started_at,
        "finished_at": workflow_finished_at,
        "duration_ms": workflow_duration_ms,
        "stages": stage_entries,
        "fallback_stage_count": fallback_stage_count,
        "warnings": workflow_warnings,
    }

    repetition_metrics = compute_repetition_metrics(presentation_plan)
    quality_gate = _evaluate_quality_gate(
        plan=presentation_plan,
        repetition_metrics=repetition_metrics,
        target_slide_count=normalized_options.get("target_slide_count", len(presentation_plan.slides)),
        deck_risk_level=final_audit.deck_risk_level,
        llm_mode=llm_mode,
    )

    results_summary = {
        "run_id": run_id,
        "reveal_path": final_paths["reveal_entry_html"],
        "pptx_path": final_paths["pptx_path"] if pptx_available else None,
        "notes_path": str(run_path / "presentation" / ("speaker_notes_repaired.json" if repair_cycle_ran else "speaker_notes.json")),
        "audit_report_path": str(run_path / ("audit/audit_report_final.json" if repair_cycle_ran else "audit/audit_report_initial.json")),
        "asset_usage_summary": {
            "extracted_assets_count": len(extracted_artifacts_bundle.extracted_assets),
            "asset_map_resolved": len(asset_map_result.map),
            "asset_map_total": len(asset_map_result.entries),
            "slides_using_real_source_figures": len(
                {
                    item.slide_number
                    for item in reveal_result.slide_render_results
                    if any(
                        (asset.source_origin == "source_paper") and bool(asset.resolved_path)
                        for asset in item.assets_used
                    )
                }
            ),
        },
        "final_risk_summary": {
            "deck_risk_level": final_audit.deck_risk_level,
            "unresolved_high_severity_findings_count": unresolved_high,
        },
        "repetition_metrics": repetition_metrics,
        "quality_gate": quality_gate,
    }

    manifest_warnings = [*workflow_warnings, *list(final_audit.global_warnings)]
    manifest_warnings.extend(quality_gate.get("issues", []))

    if not quality_gate.get("passed", True):
        workflow_warnings.append(
            "Quality gate failed; presentations were still produced for inspection."
        )

    if not quality_gate.get("passed", True):
        final_status = "failed_with_quality_gate"
    else:
        final_status = "completed_with_warnings" if (unresolved_high > 0 or fallback_stage_count > 0 or bool(manifest_warnings)) else "completed"

    final_manifest = {
        "run_id": run_id,
        "status": final_status,
        "current_stage": "A11",
        "llm_mode": llm_mode,
        "llm_mode_reason": llm_mode_reason,
        "completed_stages": completed_stages,
        "stages": stage_entries,
        "warnings": manifest_warnings,
        "errors": [],
        "artifacts": {
            "presentation_plan": first_pass_paths["presentation_plan"],
            "speaker_notes": results_summary["notes_path"],
            "generated_visuals": first_pass_paths["generated_visuals"],
            "extracted_assets": first_pass_paths["extracted_assets"],
            "asset_map": first_pass_paths["asset_map"],
            "reveal_entry_html": results_summary["reveal_path"],
            "pptx_path": results_summary["pptx_path"] or "",
            "audit_report": results_summary["audit_report_path"],
        },
        "checkpoint_state": {},
        "started_at": workflow_started_at,
        "finished_at": workflow_finished_at,
        "duration_ms": workflow_duration_ms,
        "run_summary": {
            "job_summary": job_summary,
            "fallback_stage_count": fallback_stage_count,
            "audit_findings_count": audit_findings_count,
            "unresolved_high_severity_findings_count": unresolved_high,
            "deck_risk_level": final_audit.deck_risk_level,
            "quality_gate": quality_gate,
        },
    }

    run_manager.save_json("logs/workflow_summary.json", summary)
    run_manager.save_json("logs/results_summary.json", results_summary)
    run_manager.save_json("logs/run_manifest.json", final_manifest)
    print(f"Workflow completed: {summary}")
    return {"summary": summary, "results": results_summary, "manifest": final_manifest}


def run_sequential_workflow(pdf_path: Path, *, repair_on_audit: bool = True) -> Path:
    """Backward-compatible wrapper returning only run path."""
    run_result = run_workflow(pdf_path, repair_on_audit=repair_on_audit)
    return Path(run_result["summary"]["run_path"])


def _normalize_workflow_options(raw: dict[str, Any] | None) -> dict[str, Any]:
    advanced = raw.get("advanced_options") if isinstance(raw, dict) else {}
    advanced = advanced if isinstance(advanced, dict) else {}

    presentation_style = str(raw.get("presentation_style") or "journal_club") if isinstance(raw, dict) else "journal_club"
    target_audience = str(raw.get("audience") or "research_specialists") if isinstance(raw, dict) else "research_specialists"
    language = str(raw.get("language") or "en") if isinstance(raw, dict) else "en"

    output_formats = raw.get("output_formats") if isinstance(raw, dict) else None
    if isinstance(output_formats, list):
        normalized_formats = [str(item).strip() for item in output_formats if str(item).strip() in {"reveal", "pptx"}]
        output_formats = normalized_formats or ["reveal", "pptx"]
    else:
        output_formats = ["reveal", "pptx"]

    return {
        "presentation_style": presentation_style,
        "target_audience": target_audience,
        "language": language,
        "output_formats": output_formats,
        "target_slide_count": _coerce_int(advanced.get("target_slide_count"), 12, minimum=1, maximum=40),
        "target_duration_minutes": _coerce_int(advanced.get("target_duration_minutes"), 20, minimum=5, maximum=120),
        "llm_temperature": _coerce_float(advanced.get("llm_temperature"), 0.0, minimum=0.0, maximum=1.0),
        "deterministic_mode": _coerce_bool(advanced.get("deterministic_mode"), True),
        "visual_policy": str(advanced.get("visual_policy") or "conservative"),
        "max_reference_citations_per_slide": _coerce_int(
            advanced.get("max_reference_citations_per_slide"),
            4,
            minimum=1,
            maximum=8,
        ),
        "max_slides_per_reference": _coerce_int(
            advanced.get("max_slides_per_reference"),
            3,
            minimum=1,
            maximum=10,
        ),
        "image_gen_enabled": _coerce_optional_bool(advanced.get("image_gen_enabled")),
        "image_gen_max_images_per_run": _coerce_optional_int(advanced.get("image_gen_max_images_per_run"), minimum=0, maximum=8),
    }


def _resolve_effective_llm_settings(settings: LLMSettings, options: dict[str, Any]) -> LLMSettings:
    overrides: dict[str, Any] = {
        "llm_temperature": 0.0 if options["deterministic_mode"] else options["llm_temperature"],
    }

    image_gen_enabled_override = options.get("image_gen_enabled")
    if image_gen_enabled_override is not None:
        overrides["image_gen_enabled"] = bool(image_gen_enabled_override)

    max_images_override = options.get("image_gen_max_images_per_run")
    if isinstance(max_images_override, int):
        overrides["image_gen_max_images_per_run"] = max_images_override

    return replace(settings, **overrides)


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _coerce_optional_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _coerce_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return _coerce_bool(value, False)


def _utc_timestamp() -> str:
    """Return timezone-aware UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def _resolve_llm_mode(settings: LLMSettings) -> tuple[str, str]:
    """Determine whether to use real provider calls or deterministic mock mode."""
    if settings.use_mock_llm:
        return "mocked", "USE_MOCK_LLM=true"

    if os.getenv("PYTEST_CURRENT_TEST"):
        return "mocked", "Pytest environment detected"

    if settings.provider == "openai" and settings.has_openai_config:
        return "real", f"OpenAI configured with model={settings.llm_model}"

    if settings.provider == "azure_openai" and settings.has_azure_openai_config:
        auth_mode = "entra" if settings.azure_openai_use_entra and not settings.azure_openai_api_key else "api_key"
        return "real", f"Azure OpenAI configured with deployment={settings.azure_openai_deployment}, auth={auth_mode}"

    if settings.provider == "azure_openai":
        return "mocked", "Missing Azure OpenAI config (set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT, plus API key or Entra auth)"

    if settings.provider and settings.provider != "openai":
        return "mocked", f"Unsupported provider '{settings.provider}'. Supported: openai, azure_openai"

    return "mocked", "Missing real LLM config (set LLM_PROVIDER=openai and OPENAI_API_KEY)"


def _build_workflow_llm_client(
    *,
    llm_settings: LLMSettings,
    llm_mode: str,
    source_pdf_path: Path,
    pdf_parse_output: PDFParseOutput,
    section_candidates: list[SectionCandidate],
    sections_for_analysis: list[SectionCandidate],
    references_for_summary: list[str],
    repair_on_audit: bool,
) -> LLMClient:
    """Create real or mock LLM client according to resolved workflow mode."""
    if llm_mode == "real":
        if llm_settings.provider == "azure_openai":
            primary_transport = AzureOpenAIChatTransport(
                api_key=llm_settings.azure_openai_api_key,
                endpoint=llm_settings.azure_openai_endpoint or "",
                api_version=llm_settings.azure_openai_api_version,
                deployment=llm_settings.azure_openai_deployment or llm_settings.llm_model,
                use_entra=llm_settings.azure_openai_use_entra,
                temperature=llm_settings.llm_temperature,
                timeout_seconds=llm_settings.openai_timeout_seconds,
            )

            if llm_settings.azure_openai_use_entra and not llm_settings.azure_openai_api_key:
                fallback_responses = _build_fake_responses(
                    source_pdf_path=source_pdf_path,
                    pdf_parse_output=pdf_parse_output,
                    section_candidates=section_candidates,
                    sections_for_analysis=sections_for_analysis,
                    references_for_summary=references_for_summary,
                    repair_on_audit=repair_on_audit,
                )
                transport = FallbackOnAuthErrorTransport(
                    primary=primary_transport,
                    fallback=SequentialMockTransport(fallback_responses),
                )
            else:
                transport = primary_transport

            return LLMClient(transport=transport, default_model=llm_settings.azure_openai_deployment or llm_settings.llm_model)

        transport = OpenAIChatTransport(
            api_key=llm_settings.openai_api_key,
            default_model=llm_settings.llm_model,
            base_url=llm_settings.openai_base_url,
            temperature=llm_settings.llm_temperature,
            timeout_seconds=llm_settings.openai_timeout_seconds,
        )
        return LLMClient(transport=transport, default_model=llm_settings.llm_model)

    mock_responses = _build_fake_responses(
        source_pdf_path=source_pdf_path,
        pdf_parse_output=pdf_parse_output,
        section_candidates=section_candidates,
        sections_for_analysis=sections_for_analysis,
        references_for_summary=references_for_summary,
        repair_on_audit=repair_on_audit,
    )
    return LLMClient(transport=SequentialMockTransport(mock_responses), default_model=llm_settings.llm_model)


def _materialize_generated_images(
    *,
    generated_visuals: GeneratedVisuals,
    llm_settings: LLMSettings,
    run_path: Path,
) -> tuple[dict[str, str], list[str]]:
    settings = ImageGenerationSettings(
        enabled=llm_settings.image_gen_enabled,
        model=llm_settings.image_gen_model,
        size=llm_settings.image_gen_size,
        quality=llm_settings.image_gen_quality,
        max_images_per_run=max(0, llm_settings.image_gen_max_images_per_run),
        max_retries_per_image=max(0, llm_settings.image_gen_max_retries_per_image),
        retry_delay_seconds=max(0.0, llm_settings.image_gen_retry_delay_seconds),
    )

    generator = OpenAIConceptualImageGenerator(
        api_key=llm_settings.openai_api_key,
        settings=settings,
        cache_dir=run_path.parents[0] / "_image_cache",
    )

    return generator.materialize(
        entries=generated_visuals.generated_visuals,
        run_assets_dir=run_path / "presentation" / "assets",
    )


def _categorize_repairs(audit_report: AuditReport) -> list[str]:
    """Map audit findings to targeted repair agent categories by priority."""
    categories: set[str] = set()
    high_priority = {
        "unsupported_claim": "slide",
        "overclaim": "slide",
        "artifact_distortion_risk": "visual",
        "generated_visual_overreach": "visual",
    }
    medium_priority = {
        "citation_issue": "citation",
        "omitted_limitation": "slide",
        "notes_issue": "notes",
        "translation_drift": "translation",
    }

    for slide_audit in audit_report.slide_audits:
        for finding in slide_audit.findings:
            if finding.category in high_priority:
                categories.add(high_priority[finding.category])
            elif finding.category in medium_priority:
                categories.add(medium_priority[finding.category])

    ordered = ["slide", "visual", "citation", "notes", "translation"]
    return [item for item in ordered if item in categories]


def _apply_slide_repairs(plan: PresentationPlan, audit_report: AuditReport) -> PresentationPlan:
    risky_slides = {
        audit.slide_number
        for audit in audit_report.slide_audits
        for finding in audit.findings
        if finding.category in {"unsupported_claim", "overclaim", "omitted_limitation"}
    }

    payload = plan.model_dump()
    for slide in payload["slides"]:
        if slide["slide_number"] in risky_slides:
            slide["key_points"] = slide["key_points"][:1]
            slide["must_avoid"] = sorted(set(slide.get("must_avoid", []) + ["Overclaiming", "Unsupported assertions"]))
            slide["confidence_notes"] = slide.get("confidence_notes", []) + ["Simplified during safety repair cycle."]
    payload["global_warnings"] = payload.get("global_warnings", []) + ["Slide content simplified after audit findings."]
    return PresentationPlan.model_validate(payload)


def _apply_citation_repairs(
    plan: PresentationPlan,
    audit_report: AuditReport,
    *,
    reference_index: ReferenceIndex | None = None,
) -> PresentationPlan:
    citation_slides = {
        audit.slide_number
        for audit in audit_report.slide_audits
        for finding in audit.findings
        if finding.category == "citation_issue"
    }

    payload = plan.model_dump()
    fallback_reference_labels = _collect_reference_citation_labels(payload)
    retrieved_candidates = _build_retrieved_reference_candidates(reference_index)
    if retrieved_candidates:
        fallback_reference_labels = [
            str(candidate.get("short_citation", "")).strip()
            for candidate in retrieved_candidates
            if str(candidate.get("short_citation", "")).strip()
        ]
    repaired_slide_count = 0

    for slide in payload["slides"]:
        if slide["slide_number"] not in citation_slides:
            continue

        citations = slide.get("citations", [])
        if not isinstance(citations, list):
            citations = []
        slide["citations"] = citations

        has_reference_citation = any(
            isinstance(citation, dict)
            and str(citation.get("source_kind", "")).strip() == "reference_paper"
            and str(citation.get("short_citation", "")).strip()
            for citation in citations
        )
        if has_reference_citation:
            continue

        existing_labels = {
            str(citation.get("short_citation", "")).strip().lower()
            for citation in citations
            if isinstance(citation, dict) and str(citation.get("short_citation", "")).strip()
        }

        extracted_labels = _extract_reference_mentions_from_slide(slide)
        appended = 0
        for label in extracted_labels:
            resolved_label = _resolve_retrieved_reference_citation_label(
                label,
                retrieved_candidates,
            )
            if resolved_label:
                label = resolved_label
            key = label.lower()
            if key in existing_labels:
                continue
            citations.append(
                {
                    "short_citation": label,
                    "source_kind": "reference_paper",
                    "citation_purpose": "contextual_reference",
                }
            )
            existing_labels.add(key)
            appended += 1
            if appended >= 2:
                break

        if appended == 0:
            for label in fallback_reference_labels:
                key = label.lower()
                if key in existing_labels:
                    continue
                citations.append(
                    {
                        "short_citation": label,
                        "source_kind": "reference_paper",
                        "citation_purpose": "contextual_reference",
                    }
                )
                appended = 1
                break

        if appended > 0:
            repaired_slide_count += 1

    payload["global_warnings"] = payload.get("global_warnings", []) + ["Citation coverage tightened in repair cycle."]
    if repaired_slide_count:
        payload["global_warnings"].append(
            f"Citation repair added reference-paper citations to {repaired_slide_count} slide(s)."
        )
    return PresentationPlan.model_validate(payload)


def _collect_reference_citation_labels(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue
        citations = slide.get("citations", [])
        if not isinstance(citations, list):
            continue
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            if str(citation.get("source_kind", "")).strip() != "reference_paper":
                continue
            label = str(citation.get("short_citation", "")).strip()
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            labels.append(label)
    return labels


def _extract_reference_mentions_from_slide(slide: dict[str, Any]) -> list[str]:
    text_parts: list[str] = []
    for field in ("title", "objective"):
        value = slide.get(field)
        if isinstance(value, str) and value.strip():
            text_parts.append(value)

    for field in ("key_points", "speaker_note_hooks"):
        entries = slide.get(field, [])
        if isinstance(entries, list):
            for item in entries:
                if isinstance(item, str) and item.strip():
                    text_parts.append(item)

    text = "\n".join(text_parts)
    if not text:
        return []

    labels: list[str] = []
    seen: set[str] = set()

    pair_pattern = re.compile(
        r"\b([A-Z][A-Za-z'`-]+)\s*(?:and|&)\s*([A-Z][A-Za-z'`-]+)\s*\(?((?:19|20)\d{2}[a-z]?)\)?"
    )
    et_al_pattern = re.compile(r"\b([A-Z][A-Za-z'`-]+)\s+et\s+al\.?\s*\(?((?:19|20)\d{2}[a-z]?)\)?", re.IGNORECASE)

    for match in pair_pattern.finditer(text):
        first = match.group(1)
        second = match.group(2)
        year = match.group(3)
        label = f"{first} & {second}, {year}"
        key = label.lower()
        if key not in seen:
            seen.add(key)
            labels.append(label)

    for match in et_al_pattern.finditer(text):
        surname = match.group(1)
        year = match.group(2)
        label = f"{surname} et al., {year}"
        key = label.lower()
        if key not in seen:
            seen.add(key)
            labels.append(label)

    return labels


def _apply_visual_repairs(visuals: GeneratedVisuals, audit_report: AuditReport) -> GeneratedVisuals:
    payload = visuals.model_dump()
    for item in payload.get("generated_visuals", []):
        item["safety_notes"] = item.get("safety_notes", []) + ["Re-validated for non-evidentiary framing during repair cycle."]
    payload["global_visual_warnings"] = payload.get("global_visual_warnings", []) + [
        "Visual specs were constrained to conservative explanatory usage after audit."
    ]
    return GeneratedVisuals.model_validate(payload)


def _apply_source_first_visual_policy(
    *,
    plan: PresentationPlan,
    artifact_manifest: ArtifactManifest,
    asset_map: dict[str, str],
) -> PresentationPlan:
    """Ensure source evidence visuals are prioritized over conceptual visuals where available."""
    payload = plan.model_dump()
    updated = False

    visual_type_for_artifact: dict[str, str] = {}
    artifacts_by_id: dict[str, Any] = {}
    section_artifact_candidates: dict[str, list[str]] = {}
    allowed_recommended_actions = {"reuse_directly", "crop_or_clean", "recreate_carefully"}

    def _normalized_section_key(section_id: str) -> str:
        text = str(section_id or "").strip().upper()
        match = re.match(r"^S0*(\d+)$", text)
        if match:
            return f"S{int(match.group(1))}"
        return text

    def _artifact_priority(artifact: Any) -> tuple[int, int, int, str]:
        action_rank = {
            "reuse_directly": 0,
            "crop_or_clean": 1,
            "recreate_carefully": 2,
            "replace_with_conceptual_visual": 3,
            "avoid_using": 4,
        }
        value_rank = {"high": 0, "medium": 1, "low": 2}
        risk_rank = {"low": 0, "medium": 1, "high": 2}
        return (
            action_rank.get(str(getattr(artifact, "recommended_action", "")), 9),
            value_rank.get(str(getattr(artifact, "presentation_value", "")), 9),
            risk_rank.get(str(getattr(artifact, "distortion_risk", "")), 9),
            str(getattr(artifact, "artifact_id", "")),
        )

    for artifact in artifact_manifest.artifacts:
        artifacts_by_id[artifact.artifact_id] = artifact
        if artifact.artifact_id not in asset_map:
            continue
        if not asset_map.get(artifact.artifact_id):
            continue
        if artifact.recommended_action not in allowed_recommended_actions:
            continue
        visual_type_for_artifact[artifact.artifact_id] = _map_artifact_type_to_visual_type(artifact.artifact_type)
        section_key = _normalized_section_key(artifact.section_id)
        if section_key:
            section_artifact_candidates.setdefault(section_key, []).append(artifact.artifact_id)

    for section_key, artifact_ids in section_artifact_candidates.items():
        section_artifact_candidates[section_key] = sorted(
            artifact_ids,
            key=lambda item: _artifact_priority(artifacts_by_id[item]),
        )

    used_artifact_ids: set[str] = set()
    for slide in payload.get("slides", []):
        for visual in slide.get("visuals", []):
            if visual.get("source_origin") == "source_paper" and visual.get("asset_id"):
                used_artifact_ids.add(str(visual.get("asset_id")))
        for support in slide.get("source_support", []):
            if support.get("support_type") == "source_artifact" and support.get("support_id"):
                used_artifact_ids.add(str(support.get("support_id")))

    evidence_roles = {"result", "discussion", "limitation", "contribution"}

    for slide in payload.get("slides", []):
        support_artifact_ids = [
            item.get("support_id", "")
            for item in slide.get("source_support", [])
            if item.get("support_type") == "source_artifact"
            and item.get("support_id") in visual_type_for_artifact
        ]

        if not support_artifact_ids:
            inferred_artifact_id = ""
            section_support_ids = [
                _normalized_section_key(str(item.get("support_id", "")))
                for item in slide.get("source_support", [])
                if item.get("support_type") == "source_section"
            ]

            for section_key in section_support_ids:
                candidates = section_artifact_candidates.get(section_key, [])
                if not candidates:
                    continue
                inferred_artifact_id = next((item for item in candidates if item not in used_artifact_ids), "")
                if inferred_artifact_id:
                    break

            if inferred_artifact_id:
                support_artifact_ids = [inferred_artifact_id]
                source_support = list(slide.get("source_support", []))
                source_support.append(
                    {
                        "support_type": "source_artifact",
                        "support_id": inferred_artifact_id,
                        "support_note": "Auto-policy: inferred from source section support.",
                    }
                )
                slide["source_support"] = source_support
                used_artifact_ids.add(inferred_artifact_id)
                updated = True

                notes = list(slide.get("confidence_notes", []))
                notes.append("Auto-policy: inferred source artifact from section-level support.")
                slide["confidence_notes"] = notes

        visuals = slide.get("visuals", [])
        has_source_visual = any(item.get("source_origin") == "source_paper" for item in visuals)
        conceptual_indexes = [
            idx
            for idx, item in enumerate(visuals)
            if item.get("visual_type") == "generated_conceptual" or item.get("source_origin") == "generated"
        ]

        if support_artifact_ids and not has_source_visual:
            artifact_id = support_artifact_ids[0]
            source_visual = {
                "visual_type": visual_type_for_artifact[artifact_id],
                "asset_id": artifact_id,
                "source_origin": "source_paper",
                "usage_mode": "reuse",
                "placement_hint": "left_visual_right_text",
                "why_this_visual": "Source-first policy: use available paper evidence before conceptual visuals.",
            }
            visuals.insert(0, source_visual)
            updated = True
            used_artifact_ids.add(artifact_id)

            notes = list(slide.get("confidence_notes", []))
            notes.append("Auto-policy: injected source artifact visual to preserve evidence fidelity.")
            slide["confidence_notes"] = notes

        if support_artifact_ids:
            filtered_visuals = [
                item
                for item in visuals
                if not (item.get("visual_type") == "generated_conceptual" or item.get("source_origin") == "generated")
            ]
            if len(filtered_visuals) != len(visuals):
                slide["visuals"] = filtered_visuals
                visuals = filtered_visuals
                updated = True

                notes = list(slide.get("confidence_notes", []))
                notes.append("Auto-policy: removed conceptual visual because source-support artifacts are available.")
                slide["confidence_notes"] = notes

        if slide.get("slide_role") in evidence_roles and support_artifact_ids and conceptual_indexes:
            must_avoid = list(slide.get("must_avoid", []))
            if "Do not use conceptual visuals as evidence" not in must_avoid:
                must_avoid.append("Do not use conceptual visuals as evidence")
                slide["must_avoid"] = must_avoid
                updated = True

    if updated:
        warnings = list(payload.get("global_warnings", []))
        warnings.append("Source-first visual policy adjusted slides with available source artifacts.")
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _apply_source_only_visual_policy(*, plan: PresentationPlan) -> PresentationPlan:
    """Remove conceptual generated visuals when user disables image generation."""
    payload = plan.model_dump()
    changed = False

    for slide in payload.get("slides", []):
        visuals = slide.get("visuals", [])
        if not isinstance(visuals, list):
            continue

        filtered = [
            visual
            for visual in visuals
            if not (
                visual.get("visual_type") == "generated_conceptual"
                or visual.get("source_origin") == "generated"
            )
        ]
        if len(filtered) != len(visuals):
            slide["visuals"] = filtered
            changed = True

            notes = list(slide.get("confidence_notes", []))
            notes.append("User option: generated images disabled; conceptual visuals removed.")
            slide["confidence_notes"] = notes

    if changed:
        warnings = payload.get("global_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("User option disabled generated images; source-only visual policy applied.")
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _apply_generated_visual_last_resort_policy(
    *,
    generated_visuals: GeneratedVisuals,
    presentation_plan: PresentationPlan,
    asset_map: dict[str, str],
) -> GeneratedVisuals:
    """Keep generated visuals as fallback-only when source-paper visuals are available."""
    source_backed_slides = {
        slide.slide_number
        for slide in presentation_plan.slides
        if any(
            visual.source_origin == "source_paper"
            and bool(asset_map.get(visual.asset_id))
            for visual in slide.visuals
        )
    }

    if not source_backed_slides:
        return generated_visuals

    payload = generated_visuals.model_dump()
    dropped_ids: list[str] = []
    kept_visuals: list[dict[str, Any]] = []
    for item in payload.get("generated_visuals", []):
        if item.get("slide_number") in source_backed_slides:
            dropped_ids.append(str(item.get("visual_id", "")))
            continue
        kept_visuals.append(item)

    if not dropped_ids:
        return generated_visuals

    payload["generated_visuals"] = kept_visuals
    warnings = payload.get("global_visual_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    warnings.append(
        f"Last-resort policy: suppressed generated visuals for source-backed slides ({', '.join([item for item in dropped_ids if item])})."
    )
    payload["global_visual_warnings"] = warnings
    return GeneratedVisuals.model_validate(payload)


def _enforce_slide_density_and_target_count(
    *,
    plan: PresentationPlan,
    section_analyses: list[Any],
    target_slide_count: int,
    artifact_manifest: ArtifactManifest | None = None,
    asset_map: dict[str, str] | None = None,
) -> PresentationPlan:
    """Increase slide substance and close slide-count gaps with grounded support slides."""
    payload = plan.model_dump()
    slides = payload.get("slides", [])
    if not isinstance(slides, list) or not slides:
        return plan

    target = max(1, int(target_slide_count or len(slides)))
    section_payloads: list[dict[str, Any]] = []
    for item in section_analyses or []:
        if hasattr(item, "model_dump"):
            section_payloads.append(item.model_dump())
        elif isinstance(item, dict):
            section_payloads.append(item)

    sections_by_id: dict[str, dict[str, Any]] = {}
    for section in section_payloads:
        section_id = str(section.get("section_id", "")).strip()
        if section_id:
            sections_by_id[section_id] = section

    section_artifact_candidates: dict[str, list[str]] = {}
    effective_asset_map = asset_map or {}
    if artifact_manifest is not None:
        for artifact in artifact_manifest.artifacts:
            artifact_id = str(getattr(artifact, "artifact_id", "")).strip()
            if not artifact_id or not effective_asset_map.get(artifact_id):
                continue
            section_key = _normalize_section_identifier(getattr(artifact, "section_id", ""))
            if not section_key:
                continue
            section_artifact_candidates.setdefault(section_key, []).append(artifact_id)

    for section_key, artifact_ids in section_artifact_candidates.items():
        section_artifact_candidates[section_key] = _dedupe_preserve_order(artifact_ids)

    used_source_artifact_ids: set[str] = set()
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        for visual in slide.get("visuals", []) or []:
            if not isinstance(visual, dict):
                continue
            if str(visual.get("source_origin", "")).strip().lower() != "source_paper":
                continue
            asset_id = str(visual.get("asset_id", "")).strip()
            if asset_id and asset_id.lower() != "none":
                used_source_artifact_ids.add(asset_id)

    language = str(payload.get("deck_metadata", {}).get("language", "en")).strip().lower() if isinstance(payload.get("deck_metadata", {}), dict) else "en"
    changed = False
    structure_changed = False

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        role = str(slide.get("slide_role", "")).strip().lower()
        min_points = 3 if role == "title" else 4
        max_points = 6 if role != "title" else 4

        key_points = [str(item).strip() for item in slide.get("key_points", []) if str(item).strip()]
        candidates = _build_density_candidates_for_slide(
            slide=slide,
            sections_by_id=sections_by_id,
            section_payloads=section_payloads,
            language=language,
        )
        for candidate in candidates:
            if len(key_points) >= min_points:
                break
            if candidate not in key_points:
                key_points.append(candidate)

        if role != "title":
            key_points = [_expand_sparse_key_point(point, slide, language=language) for point in key_points]

        if language == "es":
            key_points = [_localize_spanish_text_fragment(point, slide=slide) for point in key_points]

        key_points = [point for point in key_points if not _is_low_value_support_line(point)]
        key_points = _dedupe_preserve_order(key_points)

        if len(key_points) > max_points:
            key_points = key_points[:max_points]

        if key_points != slide.get("key_points", []):
            slide["key_points"] = key_points
            changed = True

        if language == "es":
            original_title = str(slide.get("title", "")).strip()
            if original_title and _looks_predominantly_english(original_title):
                slide["title"] = _default_spanish_title_for_role(role=role)
                changed = True

            objective = str(slide.get("objective", "")).strip()
            if objective and _looks_predominantly_english(objective):
                slide["objective"] = f"Desarrollar el punto central de la diapositiva: {_default_spanish_title_for_role(role=role)}."
                changed = True

    if len(slides) < target:
        addenda = _build_supporting_slides_for_target(
            existing_slides=slides,
            section_payloads=section_payloads,
            target_slide_count=target,
            language=language,
            section_artifact_candidates=section_artifact_candidates,
            used_source_artifact_ids=used_source_artifact_ids,
        )
        if addenda:
            insert_at = len(slides)
            for idx, slide in enumerate(slides):
                if not isinstance(slide, dict):
                    continue
                role = str(slide.get("slide_role", "")).strip().lower()
                title = str(slide.get("title", "")).strip().lower()
                if role == "conclusion" or title.startswith("conclusion"):
                    insert_at = idx
                    break

            slides[insert_at:insert_at] = addenda
            changed = True

    reordered_slides = _apply_structural_slide_order_policy(
        slides=slides,
        sections_by_id=sections_by_id,
    )
    if reordered_slides != slides:
        slides = reordered_slides
        changed = True
        structure_changed = True

    repetition_changed = _reduce_cross_slide_bullet_repetition(
        slides=slides,
        sections_by_id=sections_by_id,
        section_payloads=section_payloads,
        language=language,
    )
    if repetition_changed:
        changed = True

    for idx, slide in enumerate(slides, start=1):
        if isinstance(slide, dict):
            slide["slide_number"] = idx

    payload["slides"] = slides
    metadata = payload.get("deck_metadata", {})
    if isinstance(metadata, dict):
        metadata["target_slide_count"] = target
        payload["deck_metadata"] = metadata

    if changed:
        warnings = payload.get("global_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(
            "Auto-policy: increased per-slide content density and backfilled supporting slides toward target slide count."
        )
        if structure_changed:
            warnings.append(
                "Auto-policy: reordered structure to keep Abstract/Introduction context near the beginning and conclusions near the end (appendix-like slides may follow)."
            )
        if repetition_changed:
            warnings.append(
                "Auto-policy: reduced repeated long-form bullets across slides to improve content diversity."
            )
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _build_density_candidates_for_slide(
    *,
    slide: dict[str, Any],
    sections_by_id: dict[str, dict[str, Any]],
    section_payloads: list[dict[str, Any]],
    language: str,
) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".")
        if len(cleaned) < 18:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(cleaned)

    source_sections: list[dict[str, Any]] = []
    for support in slide.get("source_support", []) or []:
        if not isinstance(support, dict):
            continue
        if str(support.get("support_type", "")) != "source_section":
            continue
        support_id = str(support.get("support_id", "")).strip()
        if support_id and support_id in sections_by_id:
            source_sections.append(sections_by_id[support_id])

    if not source_sections:
        role = str(slide.get("slide_role", "")).lower()
        role_map = {
            "motivation": "framing_background",
            "problem": "problem_definition",
            "contribution": "experiment_result_interpretation",
            "method": "method_explanation",
            "result": "experiment_result_interpretation",
            "discussion": "limitations_discussion",
            "limitation": "limitations_discussion",
            "conclusion": "conclusion_takeaways",
            "appendix_like_support": "experiment_result_interpretation",
        }
        desired_role = role_map.get(role)
        if desired_role:
            for section in section_payloads:
                roles = section.get("section_role", [])
                if isinstance(roles, list) and desired_role in roles:
                    source_sections.append(section)
                    if len(source_sections) >= 2:
                        break

    for section in source_sections[:2]:
        for claim in section.get("key_claims", [])[:3]:
            if not isinstance(claim, dict):
                continue
            claim_text = str(claim.get("claim", "")).strip()
            note_text = str(claim.get("notes", "")).strip()
            if claim_text and note_text and note_text.lower() not in claim_text.lower():
                _add(f"{claim_text} ({note_text})")
            else:
                _add(claim_text)

        for detail in section.get("important_details", [])[:3]:
            _add(str(detail))

        for caution in section.get("limitations_or_cautions", [])[:2]:
            caution_prefix = "Precaucion" if language == "es" else "Caution"
            _add(f"{caution_prefix}: {str(caution).strip()}")

    return candidates


def _expand_sparse_key_point(point: str, slide: dict[str, Any], *, language: str = "en") -> str:
    cleaned = re.sub(r"\s+", " ", str(point or "")).strip()
    if len(cleaned) >= 55:
        return cleaned
    objective = re.sub(r"\s+", " ", str(slide.get("objective", "")).strip())
    if objective and objective.lower() not in cleaned.lower():
        if language == "es":
            return f"{cleaned} Esto respalda directamente: {objective}."
        return f"{cleaned} This directly supports: {objective}."
    return cleaned


def _build_supporting_slides_for_target(
    *,
    existing_slides: list[dict[str, Any]],
    section_payloads: list[dict[str, Any]],
    target_slide_count: int,
    language: str,
    section_artifact_candidates: dict[str, list[str]] | None = None,
    used_source_artifact_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    additional: list[dict[str, Any]] = []
    if len(existing_slides) >= target_slide_count:
        return additional

    curated_sections = [
        section
        for section in section_payloads
        if str(section.get("section_title", "")).strip()
        and "reference" not in str(section.get("section_title", "")).strip().lower()
    ]

    preferred_sections = [
        section
        for section in curated_sections
        if str(section.get("section_title", "")).strip().lower() not in {"abstract", "introduction"}
    ]

    if preferred_sections:
        curated_sections = preferred_sections

    has_existing_conclusion = any(
        isinstance(slide, dict)
        and (
            str(slide.get("slide_role", "")).strip().lower() == "conclusion"
            or _normalize_title_for_match(str(slide.get("title", ""))).startswith("conclusion")
        )
        for slide in existing_slides
    )
    if has_existing_conclusion:
        curated_sections = [
            section
            for section in curated_sections
            if "conclusion_takeaways" not in (section.get("section_role", []) or [])
        ]

    if not curated_sections:
        return additional

    existing_title_keys = {
        _normalize_title_for_match(str(slide.get("title", "")))
        for slide in existing_slides
        if isinstance(slide, dict)
    }
    existing_bullet_keys = {
        _normalize_bullet_key(str(point))
        for slide in existing_slides
        if isinstance(slide, dict)
        for point in (slide.get("key_points", []) or [])
        if _normalize_bullet_key(str(point))
    }

    artifact_candidates_by_section = section_artifact_candidates or {}
    used_artifacts = used_source_artifact_ids if used_source_artifact_ids is not None else set()

    needed_support = max(0, target_slide_count - len(existing_slides))
    max_support_slides = needed_support
    if max_support_slides <= 0:
        return additional

    def _windowed_pick(items: list[Any], *, start: int, size: int) -> list[Any]:
        if size <= 0 or not items:
            return []
        count = len(items)
        picked: list[Any] = []
        for offset in range(min(size, count)):
            picked.append(items[(start + offset) % count])
        return picked

    start_number = len(existing_slides) + 1
    section_usage_counts: dict[str, int] = {}
    cursor = 0
    max_iterations = max(max_support_slides * 6, len(curated_sections) * 6, 40)
    iterations = 0
    while len(additional) < max_support_slides:
        iterations += 1
        if iterations > max_iterations:
            break
        section = curated_sections[cursor % len(curated_sections)]
        cursor += 1
        section_key = str(section.get("section_id", "")).strip() or f"idx_{cursor}"
        usage_index = section_usage_counts.get(section_key, 0)
        section_usage_counts[section_key] = usage_index + 1
        role_list = section.get("section_role", [])
        primary_role = role_list[0] if isinstance(role_list, list) and role_list else "experiment_result_interpretation"
        slide_role = {
            "framing_background": "motivation",
            "problem_definition": "problem",
            "method_explanation": "method",
            "experiment_result_interpretation": "result",
            "limitations_discussion": "discussion",
            "conclusion_takeaways": "conclusion",
        }.get(str(primary_role), "appendix_like_support")

        key_points: list[str] = []
        claim_items = section.get("key_claims", [])
        if not isinstance(claim_items, list):
            claim_items = []
        detail_items = section.get("important_details", [])
        if not isinstance(detail_items, list):
            detail_items = []

        claim_window = _windowed_pick(claim_items, start=usage_index * 3, size=3)
        detail_window = _windowed_pick(detail_items, start=usage_index * 2, size=2)

        for claim in claim_window:
            if isinstance(claim, dict):
                claim_text = str(claim.get("claim", "")).strip()
                note_text = str(claim.get("notes", "")).strip()
                if claim_text and note_text and note_text.lower() not in claim_text.lower():
                    combined = f"{claim_text} ({note_text})"
                    key_points.append(combined)
                elif claim_text:
                    key_points.append(claim_text)

        for detail in detail_window:
            detail_text = str(detail).strip()
            if detail_text and detail_text not in key_points:
                key_points.append(detail_text)

        if len(key_points) < 4:
            summary = str(section.get("summary", "")).strip()
            if summary and summary not in key_points:
                key_points.append(summary)

        key_points = [
            _expand_sparse_key_point(item, {"objective": section.get("why_it_matters", "")}, language=language)
            for item in key_points[:6]
        ]
        key_points = _dedupe_preserve_order(key_points)
        if len(key_points) < 2:
            continue

        section_id = str(section.get("section_id", "")).strip() or f"s{start_number + len(additional)}"
        section_lookup_key = _normalize_section_identifier(section_id)
        selected_source_artifact_id = ""
        if section_lookup_key and section_lookup_key in artifact_candidates_by_section:
            selected_source_artifact_id = next(
                (
                    artifact_id
                    for artifact_id in artifact_candidates_by_section.get(section_lookup_key, [])
                    if artifact_id not in used_artifacts
                ),
                "",
            )

        if selected_source_artifact_id:
            used_artifacts.add(selected_source_artifact_id)
        default_section_title = "Analisis de soporte" if language == "es" else "Supporting analysis"
        section_title = str(section.get("section_title", default_section_title)).strip()
        if language == "es" and _looks_predominantly_english(section_title):
            section_title = _default_spanish_title_for_role(role=slide_role)
        support_suffix = "Detalle de apoyo" if language == "es" else "Supporting Detail"
        candidate_title = f"{section_title}: {support_suffix}"
        title = candidate_title
        normalized_title = _normalize_title_for_match(title)
        if normalized_title in existing_title_keys:
            sequence = 2
            while normalized_title in existing_title_keys and sequence <= 999:
                if language == "es":
                    title = f"{candidate_title} ({sequence})"
                else:
                    title = f"{candidate_title} ({sequence})"
                normalized_title = _normalize_title_for_match(title)
                sequence += 1
            if normalized_title in existing_title_keys:
                continue
        existing_title_keys.add(normalized_title)

        slide_number = start_number + len(additional)

        objective = (
            "Agregar detalle basado en la fuente que no cabia en la narrativa principal."
            if language == "es"
            else "Add source-grounded detail that did not fit in the core narrative slides."
        )
        if language == "es":
            key_points = [_localize_spanish_text_fragment(item, slide={"slide_role": slide_role, "objective": objective}) for item in key_points]
        key_points = [item for item in key_points if not _is_low_value_support_line(item)]
        key_points = _dedupe_preserve_order(key_points)
        key_points = [item for item in key_points if _normalize_bullet_key(item) not in existing_bullet_keys]
        if len(key_points) < 2:
            continue
        must_avoid = (
            ["No introducir afirmaciones no sustentadas por la seccion fuente."]
            if language == "es"
            else ["Introducing claims not grounded in the source section."]
        )
        support_note = (
            "Expandida desde el analisis de seccion para mejorar profundidad y cobertura del objetivo."
            if language == "es"
            else "Expanded from section analysis to improve depth and target coverage."
        )
        short_citation = "Articulo fuente" if language == "es" else "Source paper"
        speaker_notes = (
            [
                "Usa esta diapositiva para discusion tecnica mas profunda solo si el tiempo lo permite.",
                "Conecta cada punto con la seccion fuente analizada.",
            ]
            if language == "es"
            else [
                "Use this slide for deeper technical discussion only if time allows.",
                "Tie each bullet directly to the analyzed source section.",
            ]
        )
        confidence_note = (
            "Auto-policy: se agrego una diapositiva de apoyo para cumplir el total solicitado de diapositivas."
            if language == "es"
            else "Auto-policy: supplemental support slide added to satisfy requested slide count."
        )

        source_support = [
            {
                "support_type": "source_section",
                "support_id": section_id,
                "support_note": support_note,
            }
        ]
        if selected_source_artifact_id:
            source_support.append(
                {
                    "support_type": "source_artifact",
                    "support_id": selected_source_artifact_id,
                    "support_note": "Auto-policy: selected unused source artifact for support-slide visual coverage.",
                }
            )

        visuals = [
            {
                "visual_type": "text_only",
                "asset_id": "none",
                "source_origin": "none",
                "usage_mode": "none",
                "placement_hint": "left_visual_right_text",
                "why_this_visual": (
                    "Diapositiva centrada en texto para conservar detalle denso sustentado en la fuente."
                    if language == "es"
                    else "Text-first support slide to retain dense, source-grounded detail."
                ),
            }
        ]
        if selected_source_artifact_id:
            visuals = [
                {
                    "visual_type": "source_figure",
                    "asset_id": selected_source_artifact_id,
                    "source_origin": "source_paper",
                    "usage_mode": "reuse",
                    "placement_hint": "left_visual_right_text",
                    "why_this_visual": "Auto-policy: use an unused mapped source artifact to increase visual evidence coverage.",
                }
            ]

        additional.append(
            {
                "slide_number": slide_number,
                "slide_role": slide_role,
                "title": title,
                "objective": objective,
                "key_points": key_points,
                "must_avoid": must_avoid,
                "visuals": visuals,
                "source_support": source_support,
                "citations": [
                    {
                        "short_citation": short_citation,
                        "source_kind": "source_paper",
                        "citation_purpose": "source_of_claim",
                    }
                ],
                "speaker_note_hooks": speaker_notes,
                "confidence_notes": [confidence_note],
                "layout_hint": "two_column",
            }
        )
        existing_bullet_keys.update(_normalize_bullet_key(item) for item in key_points if _normalize_bullet_key(item))

    return additional


def _apply_structural_slide_order_policy(
    *,
    slides: list[dict[str, Any]],
    sections_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Favor early context framing and keep conclusions at the end of the core narrative."""
    if not slides:
        return slides

    context_titles = {"abstract", "introduction"}

    def _role(slide: dict[str, Any]) -> str:
        return str(slide.get("slide_role", "")).strip().lower()

    def _title(slide: dict[str, Any]) -> str:
        return _normalize_title_for_match(str(slide.get("title", "")))

    def _is_title_slide(slide: dict[str, Any]) -> bool:
        return _role(slide) == "title"

    def _is_appendix_like(slide: dict[str, Any]) -> bool:
        role = _role(slide)
        title = _title(slide)
        return role == "appendix_like_support" or title.startswith("appendix")

    def _is_conclusion(slide: dict[str, Any]) -> bool:
        role = _role(slide)
        title = _title(slide)
        return role == "conclusion" or title.startswith("conclusion")

    def _is_intro_or_abstract_context(slide: dict[str, Any]) -> bool:
        title = _title(slide)
        if title.startswith("abstract") or title.startswith("introduction"):
            return True

        for support in slide.get("source_support", []) or []:
            if not isinstance(support, dict):
                continue
            if str(support.get("support_type", "")).strip().lower() != "source_section":
                continue
            support_id = str(support.get("support_id", "")).strip()
            if not support_id:
                continue
            section = sections_by_id.get(support_id, {})
            section_title = str(section.get("section_title", "")).strip().lower()
            if section_title in context_titles:
                return True

        return False

    title_slides = [slide for slide in slides if isinstance(slide, dict) and _is_title_slide(slide)]
    remaining = [slide for slide in slides if isinstance(slide, dict) and not _is_title_slide(slide)]

    context_slides = [slide for slide in remaining if _is_intro_or_abstract_context(slide)]
    non_context = [slide for slide in remaining if not _is_intro_or_abstract_context(slide)]

    conclusions = [slide for slide in non_context if _is_conclusion(slide)]
    appendices = [slide for slide in non_context if _is_appendix_like(slide)]
    core_non_context = [
        slide
        for slide in non_context
        if not _is_conclusion(slide) and not _is_appendix_like(slide)
    ]

    ordered = [*title_slides, *context_slides, *core_non_context, *conclusions, *appendices]
    if len(ordered) != len([slide for slide in slides if isinstance(slide, dict)]):
        return slides
    return ordered


def _normalize_title_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _normalize_section_identifier(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    match = re.match(r"^S0*(\d+)$", text)
    if match:
        return f"S{int(match.group(1))}"
    return text


def _looks_predominantly_english(text: str) -> bool:
    words = re.findall(r"[a-zA-Z]+", str(text or "").lower())
    english_markers = {
        "the",
        "this",
        "that",
        "with",
        "from",
        "for",
        "and",
        "are",
        "is",
        "supports",
        "results",
        "method",
        "slide",
        "key",
        "findings",
        "prioritizing",
        "measuring",
        "outcomes",
        "exposure",
    }
    spanish_markers = {"el", "la", "los", "las", "con", "para", "de", "que", "y", "es", "son"}
    english_hits = sum(1 for word in words if word in english_markers)
    spanish_hits = sum(1 for word in words if word in spanish_markers)
    if len(words) < 5:
        return english_hits >= 1 and spanish_hits == 0
    ratio = english_hits / max(len(words), 1)
    return (english_hits >= 2 and english_hits > spanish_hits) or (len(words) >= 4 and ratio >= 0.45 and spanish_hits == 0)


def _support_slide_fallback_lines(*, language: str) -> list[str]:
    if language == "es":
        return [
            "Esta diapositiva resume evidencia adicional vinculada a la seccion fuente.",
            "Se destacan implicaciones tecnicas que complementan la narrativa principal.",
            "El contenido prioriza trazabilidad a resultados reportados en el articulo.",
            "Estos puntos se incluyen para profundizar la discusion con respaldo documental.",
        ]
    return [
        "This slide summarizes additional evidence linked to the source section.",
        "It highlights technical implications that complement the core narrative.",
        "The content prioritizes traceability to results reported in the paper.",
        "These points are included to deepen discussion with documented support.",
    ]


def _is_low_value_support_line(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not lowered:
        return True
    placeholders = [
        "esta diapositiva de apoyo conserva detalles tecnicos basados en la fuente para la discusion",
        "this support slide preserves source-grounded detail for technical discussion",
    ]
    return any(item in lowered for item in placeholders)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(str(value).strip())
    return ordered


def _normalize_bullet_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _reduce_cross_slide_bullet_repetition(
    *,
    slides: list[dict[str, Any]],
    sections_by_id: dict[str, dict[str, Any]],
    section_payloads: list[dict[str, Any]],
    language: str,
) -> bool:
    if not slides:
        return False

    counts: dict[str, int] = {}
    samples: dict[str, str] = {}
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        for point in slide.get("key_points", []) or []:
            text = str(point or "").strip()
            key = _normalize_bullet_key(text)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            samples.setdefault(key, text)

    overused = {
        key
        for key, count in counts.items()
        if count > 1 and len(samples.get(key, "")) >= 70
    }
    if not overused:
        return False

    changed = False
    seen: dict[str, int] = {}

    for slide in slides:
        if not isinstance(slide, dict):
            continue

        role = str(slide.get("slide_role", "")).strip().lower()
        min_points = 3 if role == "title" else 4
        original_points = [str(item).strip() for item in (slide.get("key_points", []) or []) if str(item).strip()]
        kept_points: list[str] = []
        local_seen: set[str] = set()

        for point in original_points:
            key = _normalize_bullet_key(point)
            if not key or key in local_seen:
                continue

            if key in overused and seen.get(key, 0) >= 1:
                changed = True
                continue

            kept_points.append(point)
            local_seen.add(key)
            seen[key] = seen.get(key, 0) + 1

        if len(kept_points) < min_points:
            candidates = _build_density_candidates_for_slide(
                slide=slide,
                sections_by_id=sections_by_id,
                section_payloads=section_payloads,
                language=language,
            )
            for candidate in candidates:
                if len(kept_points) >= min_points:
                    break
                candidate_key = _normalize_bullet_key(candidate)
                if not candidate_key or candidate_key in local_seen:
                    continue
                if candidate_key in overused and seen.get(candidate_key, 0) >= 1:
                    continue
                kept_points.append(candidate)
                local_seen.add(candidate_key)
                seen[candidate_key] = seen.get(candidate_key, 0) + 1
                changed = True

        normalized_points = _dedupe_preserve_order(kept_points)
        if normalized_points != original_points:
            slide["key_points"] = normalized_points
            changed = True

    return changed


def _default_spanish_title_for_role(*, role: str) -> str:
    mapping = {
        "motivation": "Motivacion",
        "problem": "Planteamiento del problema",
        "contribution": "Contribuciones principales",
        "method": "Metodologia",
        "result": "Resultados clave",
        "discussion": "Discusion",
        "conclusion": "Conclusiones",
        "appendix_like_support": "Analisis de apoyo",
    }
    return mapping.get(str(role or "").strip().lower(), "Analisis de apoyo")


def _localize_spanish_text_fragment(text: str, *, slide: dict[str, Any]) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned or not _looks_predominantly_english(cleaned):
        return cleaned

    lower = cleaned.lower()
    replacements = [
        (
            "observed exposure quantifies the gap between theoretical ai capabilities and actual usage in professional settings",
            "La exposicion observada cuantifica la brecha entre la capacidad teorica de la IA y su uso real en contextos profesionales.",
        ),
        (
            "a new measure of ai displacement risk",
            "Una nueva medida de riesgo de desplazamiento por IA.",
        ),
        (
            "historical examples",
            "Ejemplos historicos muestran la dificultad de anticipar disrupciones laborales.",
        ),
        (
            "theoretical capability",
            "La capacidad teorica se evalua con metricas de factibilidad por tarea.",
        ),
        (
            "observed exposure adjusts theoretical capability",
            "La exposicion observada ajusta la capacidad teorica segun uso real en el trabajo.",
        ),
    ]
    for source, target in replacements:
        if source in lower:
            return target

    objective = re.sub(r"\s+", " ", str(slide.get("objective", "")).strip())
    if objective:
        return f"Punto clave relacionado con: {objective}."
    role = str(slide.get("slide_role", "")).strip().lower()
    return f"Punto de apoyo para { _default_spanish_title_for_role(role=role).lower() }."


def _map_artifact_type_to_visual_type(artifact_type: str) -> str:
    if artifact_type == "table":
        return "source_table"
    if artifact_type in {"plot", "chart"}:
        return "source_chart"
    if artifact_type == "diagram":
        return "source_diagram"
    return "source_figure"


def _apply_reference_citation_policy(
    *,
    plan: PresentationPlan,
    reference_index: ReferenceIndex,
    reference_summaries: list[ReferenceSummary],
    max_reference_citations_per_slide: int = 4,
    max_slides_per_reference: int = 3,
) -> PresentationPlan:
    """Inject reference-paper citations when slide content references external works.

    This guard uses A5 recommendation signals and lightweight text matching to
    ensure extracted references are visible in final slide citations.
    """
    payload = plan.model_dump()
    slides = payload.get("slides", [])
    if not isinstance(slides, list) or not slides:
        return plan

    reference_entries = {entry.reference_id: entry for entry in reference_index.reference_index}

    citation_cap = max(1, int(max_reference_citations_per_slide or 4))
    reference_reuse_cap = max(1, int(max_slides_per_reference or 3))
    candidates: list[dict[str, Any]] = []
    for summary in reference_summaries:
        mention = summary.mention_recommendation
        if not mention.should_mention_in_final_deck:
            continue
        if summary.confidence not in {"high", "medium"}:
            continue

        entry = reference_entries.get(summary.reference_id)
        if entry is None:
            continue
        if str(entry.retrieval_status) != "retrieved":
            continue

        short_citation, tokens = _build_reference_citation_signature(
            summary=summary,
            entry=entry,
        )
        if not short_citation:
            continue

        role_hints = _build_reference_role_hints(summary)
        base_priority = _reference_candidate_base_priority(summary)

        candidates.append(
            {
                "reference_id": summary.reference_id,
                "short_citation": short_citation,
                "tokens": tokens,
                "role_hints": role_hints,
                "base_priority": base_priority,
            }
        )

    if not candidates:
        return plan

    usage_counts = _build_reference_usage_counts(slides=slides, candidates=candidates)

    changed = False
    for slide in slides:
        if not isinstance(slide, dict):
            continue

        slide_citations = slide.get("citations", [])
        if not isinstance(slide_citations, list):
            slide_citations = []
            slide["citations"] = slide_citations

        if str(slide.get("slide_role", "")) == "title":
            filtered_title_citations = [
                citation
                for citation in slide_citations
                if not (isinstance(citation, dict) and citation.get("source_kind") == "reference_paper")
            ]
            if len(filtered_title_citations) != len(slide_citations):
                slide["citations"] = filtered_title_citations
                slide_citations = filtered_title_citations
                changed = True
            continue

        existing_reference_count = sum(
            1
            for citation in slide_citations
            if isinstance(citation, dict) and str(citation.get("source_kind", "")).strip() == "reference_paper"
        )
        if existing_reference_count >= citation_cap:
            continue

        searchable = _build_slide_search_text(slide)
        slide_role = str(slide.get("slide_role", "")).strip()
        ranked = _rank_reference_candidates_for_slide(
            search_text=searchable,
            slide_role=slide_role,
            candidates=candidates,
            existing_citations=slide_citations,
            usage_counts=usage_counts,
            max_slides_per_reference=reference_reuse_cap,
        )
        if not ranked:
            continue

        slots_remaining = max(0, citation_cap - existing_reference_count)
        if slots_remaining == 0:
            continue

        for candidate in ranked[:slots_remaining]:
            slide_citations.append(
                {
                    "short_citation": candidate["short_citation"],
                    "source_kind": "reference_paper",
                    "citation_purpose": _infer_reference_citation_purpose(slide_role=slide_role, candidate=candidate),
                }
            )
            usage_key = str(candidate.get("short_citation", "")).strip().lower()
            if usage_key:
                usage_counts[usage_key] = usage_counts.get(usage_key, 0) + 1
            changed = True

    if changed:
        warnings = payload.get("global_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(
            "Auto-policy: injected relevance-filtered reference-paper citations from retrieved references "
            f"(max_per_slide={citation_cap}, max_slides_per_reference={reference_reuse_cap})."
        )
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _normalize_reference_citation_labels(
    *,
    plan: PresentationPlan,
    reference_index: ReferenceIndex,
) -> PresentationPlan:
    """Normalize reference-paper citation labels to stable author-year forms."""
    payload = plan.model_dump()
    slides = payload.get("slides", [])
    if not isinstance(slides, list) or not slides:
        return plan

    candidates = _build_reference_normalization_candidates(reference_index)

    changed = False
    for slide in slides:
        if not isinstance(slide, dict):
            continue

        citations = slide.get("citations", [])
        if not isinstance(citations, list):
            continue

        normalized: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()

        for citation in citations:
            if not isinstance(citation, dict):
                continue

            source_kind = str(citation.get("source_kind", "")).strip() or "source_paper"
            short_raw = str(citation.get("short_citation", "")).strip()
            short_clean = re.sub(r"\\s*\\|\\s*", " | ", short_raw)
            short_clean = short_clean.split("|", 1)[0].strip() if "|" in short_clean else short_clean

            if source_kind == "reference_paper":
                if _REFERENCE_ID_PATTERN.search(short_clean):
                    unresolved_label = _format_unresolved_reference_citation_label(short_clean)
                    if unresolved_label != short_clean:
                        changed = True
                    short_clean = unresolved_label
                    normalized_ref = None
                else:
                    normalized_ref = _match_reference_canonical_label(short_clean, candidates)
                if normalized_ref:
                    if normalized_ref != short_clean:
                        changed = True
                    short_clean = normalized_ref
                elif not _REFERENCE_CITATION_FORMAT.match(short_clean):
                    short_clean = _format_unresolved_reference_citation_label(short_clean)
                    changed = True

            dedupe_key = (source_kind, short_clean)
            if dedupe_key in seen_keys:
                changed = True
                continue
            seen_keys.add(dedupe_key)

            updated_citation = dict(citation)
            updated_citation["short_citation"] = short_clean
            normalized.append(updated_citation)

        if normalized != citations:
            slide["citations"] = normalized
            changed = True

    if changed:
        warnings = payload.get("global_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("Auto-policy: normalized reference citation labels for consistency.")
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _apply_citation_purpose_policy(*, plan: PresentationPlan) -> PresentationPlan:
    """Attach a concise explanation purpose to each slide citation."""
    payload = plan.model_dump()
    changed = False

    for slide in payload.get("slides", []):
        if not isinstance(slide, dict):
            continue

        role = str(slide.get("slide_role", "")).strip()
        citations = slide.get("citations", [])
        if not isinstance(citations, list):
            continue

        for citation in citations:
            if not isinstance(citation, dict):
                continue

            purpose = str(citation.get("citation_purpose", "")).strip()
            if purpose in {"source_of_claim", "method_background", "attribution"}:
                continue
            if purpose and purpose != "contextual_reference":
                continue

            source_kind = str(citation.get("source_kind", "")).strip()
            inferred = "contextual_reference"
            if source_kind == "source_paper":
                inferred = "source_of_claim"
            if role in {"title"}:
                inferred = "attribution"
            elif role in {"method"} and source_kind == "reference_paper":
                inferred = "method_background"

            citation["citation_purpose"] = inferred
            changed = True

    if changed:
        warnings = payload.get("global_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append("Auto-policy: inferred citation purposes for explainability.")
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _enforce_retrieved_reference_citation_policy(
    *,
    plan: PresentationPlan,
    reference_index: ReferenceIndex,
) -> PresentationPlan:
    """Drop reference-paper citations/support that do not map to retrieved references."""
    payload = plan.model_dump()
    slides = payload.get("slides", [])
    if not isinstance(slides, list) or not slides:
        return plan

    retrieved_candidates = _build_retrieved_reference_candidates(reference_index)
    retrieved_ids = {
        str(candidate.get("reference_id", "")).strip().upper()
        for candidate in retrieved_candidates
        if str(candidate.get("reference_id", "")).strip()
    }
    retrieved_label_map = {
        str(candidate.get("short_key", "")).strip(): str(candidate.get("short_citation", "")).strip()
        for candidate in retrieved_candidates
        if str(candidate.get("short_key", "")).strip() and str(candidate.get("short_citation", "")).strip()
    }
    retrieved_id_map = {
        str(candidate.get("reference_id", "")).strip().upper(): str(candidate.get("short_citation", "")).strip()
        for candidate in retrieved_candidates
        if str(candidate.get("reference_id", "")).strip() and str(candidate.get("short_citation", "")).strip()
    }

    changed = False
    dropped_citations = 0
    dropped_supports = 0

    for slide in slides:
        if not isinstance(slide, dict):
            continue

        citations = slide.get("citations", [])
        if isinstance(citations, list):
            filtered_citations: list[dict[str, Any]] = []
            for citation in citations:
                if not isinstance(citation, dict):
                    continue

                if str(citation.get("source_kind", "")).strip() != "reference_paper":
                    filtered_citations.append(citation)
                    continue

                short_citation = str(citation.get("short_citation", "")).strip()
                reference_id_match = _REFERENCE_ID_PATTERN.search(short_citation)
                reference_id = reference_id_match.group(0).upper() if reference_id_match else ""
                short_key = _normalize_citation_label_key(short_citation)

                if reference_id and reference_id in retrieved_ids:
                    canonical = retrieved_id_map.get(reference_id, short_citation)
                    if canonical and canonical != short_citation:
                        citation["short_citation"] = canonical
                        changed = True
                    filtered_citations.append(citation)
                    continue

                direct_match = retrieved_label_map.get(short_key)
                if direct_match:
                    if direct_match != short_citation:
                        citation["short_citation"] = direct_match
                        changed = True
                    filtered_citations.append(citation)
                    continue

                resolved_label = _resolve_retrieved_reference_citation_label(short_citation, retrieved_candidates)
                if resolved_label:
                    if resolved_label != short_citation:
                        citation["short_citation"] = resolved_label
                        changed = True
                    filtered_citations.append(citation)
                    continue

                dropped_citations += 1

            if filtered_citations != citations:
                slide["citations"] = filtered_citations
                changed = True

        source_support = slide.get("source_support", [])
        if isinstance(source_support, list):
            filtered_support: list[dict[str, Any]] = []
            for support in source_support:
                if not isinstance(support, dict):
                    continue

                if str(support.get("support_type", "")).strip() != "reference_summary":
                    filtered_support.append(support)
                    continue

                support_id = str(support.get("support_id", "")).strip().upper()
                if support_id and support_id in retrieved_ids:
                    filtered_support.append(support)
                    continue

                dropped_supports += 1

            if filtered_support != source_support:
                slide["source_support"] = filtered_support
                changed = True

    if changed:
        warnings = payload.get("global_warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(
            "Auto-policy: removed non-retrieved reference-paper citations/support before rendering "
            f"(dropped_citations={dropped_citations}, dropped_reference_support={dropped_supports})."
        )
        payload["global_warnings"] = warnings

    return PresentationPlan.model_validate(payload)


def _build_reference_normalization_candidates(reference_index: ReferenceIndex) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in reference_index.reference_index:
        short, tokens = _build_reference_citation_signature_from_entry(entry=entry)
        if not short:
            continue
        candidates.append(
            {
                "short": short,
                "tokens": tokens,
            }
        )
    return candidates


def _build_retrieved_reference_candidates(reference_index: ReferenceIndex | None) -> list[dict[str, Any]]:
    if reference_index is None:
        return []

    candidates: list[dict[str, Any]] = []
    for entry in reference_index.reference_index:
        if str(entry.retrieval_status) != "retrieved":
            continue

        short_citation, tokens = _build_reference_citation_signature_from_entry(entry=entry)
        short_citation = str(short_citation).strip()
        if not short_citation:
            continue

        year = str(entry.parsed_reference.year or "").strip().lower() if entry.parsed_reference else ""
        surnames: set[str] = set()
        if entry.parsed_reference:
            for author in list(entry.parsed_reference.authors)[:2]:
                surname = str(author).strip().split(" ")[-1].lower()
                surname = re.sub(r"[^a-z0-9]", "", surname)
                if surname:
                    surnames.add(surname)

        candidate_tokens = set(tokens)
        candidate_tokens.update(surnames)
        if year:
            candidate_tokens.add(year)

        candidates.append(
            {
                "reference_id": str(entry.reference_id).strip().upper(),
                "short_citation": short_citation,
                "short_key": _normalize_citation_label_key(short_citation),
                "tokens": candidate_tokens,
                "year": year,
                "surnames": surnames,
            }
        )

    return candidates


def _normalize_citation_label_key(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""

    text = text.replace("(", " ").replace(")", " ")
    text = re.sub(r"\bet\s+al\b", "et al", text)
    text = re.sub(r"[^a-z0-9&\s,]", " ", text)
    text = re.sub(r"\s*&\s*", " & ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:")
    return text


def _resolve_retrieved_reference_citation_label(
    citation_text: str,
    retrieved_candidates: list[dict[str, Any]],
) -> str | None:
    text = _normalize_citation_label_key(citation_text)
    if not text or not retrieved_candidates:
        return None

    years = set(match.lower() for match in _YEAR_PATTERN.findall(text))
    text_tokens = set(re.findall(r"[a-z0-9]+", text))

    best_candidate: dict[str, Any] | None = None
    best_score = 0

    for candidate in retrieved_candidates:
        candidate_year = str(candidate.get("year", "")).strip().lower()
        if years and candidate_year and candidate_year not in years:
            continue

        candidate_tokens = {
            str(token).lower()
            for token in candidate.get("tokens", set())
            if str(token).strip()
        }
        if not candidate_tokens:
            continue

        token_overlap = len(text_tokens & candidate_tokens)
        surname_overlap = len(
            {
                str(token).lower()
                for token in candidate.get("surnames", set())
                if str(token).strip()
            }
            & text_tokens
        )
        if surname_overlap == 0:
            continue

        score = token_overlap + surname_overlap
        if years and candidate_year:
            score += 1

        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None:
        return None
    if best_score < 2:
        return None

    return str(best_candidate.get("short_citation", "")).strip() or None


def _build_reference_citation_signature_from_entry(*, entry: Any) -> tuple[str, set[str]]:
    parsed = entry.parsed_reference
    authors = list(parsed.authors) if parsed else []
    year = str(parsed.year or "").strip() if parsed else ""
    title = str(parsed.title or "").strip() if parsed else ""

    short = f"Reference {entry.reference_id}"
    if len(authors) >= 2 and year:
        first = str(authors[0]).split()[-1]
        second = str(authors[1]).split()[-1]
        if first and second:
            short = f"{first} & {second}, {year}"
    elif authors and year:
        first = str(authors[0]).split()[-1]
        if first:
            short = f"{first} et al., {year}"
    elif authors:
        first = str(authors[0]).split()[-1]
        if first:
            short = f"{first} et al."

    tokens: set[str] = set()
    for author in authors[:2]:
        surname = str(author).split()[-1].lower()
        if surname:
            tokens.add(surname)
    if year:
        tokens.add(year.lower())
    for token in re.findall(r"[A-Za-z]{5,}", title.lower()):
        tokens.add(token)
        if len(tokens) >= 12:
            break

    return short, tokens


def _match_reference_canonical_label(citation_text: str, candidates: list[dict[str, Any]]) -> str | None:
    text = str(citation_text or "").strip().lower()
    if not text:
        return None

    best_short: str | None = None
    best_score = 0

    for candidate in candidates:
        score = 0
        for token in candidate["tokens"]:
            if token and token in text:
                score += 1
        if score > best_score:
            best_score = score
            best_short = str(candidate["short"])

    if best_score > 0:
        return best_short
    if len(candidates) == 1:
        return str(candidates[0]["short"])
    return None


def _build_reference_citation_signature(*, summary: ReferenceSummary, entry: Any) -> tuple[str, set[str]]:
    authors = list(entry.parsed_reference.authors) if entry.parsed_reference else []
    year = str(entry.parsed_reference.year or "").strip() if entry.parsed_reference else ""
    title = str(summary.reference_title or "").strip()

    surname = ""
    if authors:
        first_author = str(authors[0]).strip()
        if first_author:
            surname = first_author.split()[-1]

    if surname and year:
        short = f"{surname} et al., {year}"
    elif surname:
        short = f"{surname} et al."
    else:
        short = f"Reference {summary.reference_id}"

    tokens: set[str] = set()
    if surname:
        tokens.add(surname.lower())
    if year:
        tokens.add(year.lower())
    if title:
        for token in re.findall(r"[A-Za-z]{5,}", title.lower()):
            tokens.add(token)
            if len(tokens) >= 8:
                break

    return short, tokens


def _build_slide_search_text(slide: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("title", "objective"):
        value = slide.get(field)
        if isinstance(value, str):
            parts.append(value)
    for field in ("key_points", "speaker_note_hooks"):
        value = slide.get(field, [])
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
    return " ".join(parts).lower()


def _build_reference_role_hints(summary: ReferenceSummary) -> set[str]:
    role_hints: set[str] = set()

    relation_map = {
        "method_ancestry": {"method"},
        "benchmark_dataset_context": {"result", "method"},
        "comparison_baseline_interpretation": {"result", "discussion"},
        "supporting_evidence": {"result", "discussion"},
        "limitation_or_contrast": {"limitation", "discussion"},
        "background_context": {"motivation", "problem", "discussion", "conclusion"},
    }
    for relation in summary.relation_to_source_paper.relation_type:
        role_hints.update(relation_map.get(str(relation), set()))

    usage_map = {
        "method_context": {"method"},
        "result_context": {"result", "discussion"},
        "comparison": {"result", "discussion"},
        "limitation_context": {"limitation", "discussion"},
        "background": {"motivation", "problem", "discussion", "conclusion"},
    }
    for point in summary.useful_points_for_main_presentation:
        role_hints.update(usage_map.get(str(point.usage_type), set()))

    return role_hints


def _reference_candidate_base_priority(summary: ReferenceSummary) -> int:
    score = 0
    confidence_score = {"high": 3, "medium": 2, "low": 0}
    importance_score = {"high": 3, "medium": 2, "low": 1}
    scope_score = {
        "one_supporting_slide_note": 3,
        "one_bullet_context": 2,
        "passing_mention": 1,
        "none": 0,
    }

    score += confidence_score.get(summary.confidence, 0)
    score += importance_score.get(summary.relation_to_source_paper.importance_for_source_presentation, 0)
    score += scope_score.get(summary.mention_recommendation.recommended_scope, 0)

    strong_points = sum(1 for point in summary.useful_points_for_main_presentation if point.support_strength == "strong")
    moderate_points = sum(1 for point in summary.useful_points_for_main_presentation if point.support_strength == "moderate")
    score += min(2, strong_points)
    if strong_points == 0:
        score += min(1, moderate_points)

    return score


def _rank_reference_candidates_for_slide(
    *,
    search_text: str,
    slide_role: str,
    candidates: list[dict[str, Any]],
    existing_citations: list[Any],
    usage_counts: dict[str, int],
    max_slides_per_reference: int,
) -> list[dict[str, Any]]:
    used = {
        str(item.get("short_citation", "")).strip().lower()
        for item in existing_citations
        if isinstance(item, dict)
    }

    ranked: list[tuple[int, dict[str, Any]]] = []
    for candidate in candidates:
        short_key = str(candidate.get("short_citation", "")).strip().lower()
        if not short_key or short_key in used:
            continue
        if usage_counts.get(short_key, 0) >= max_slides_per_reference:
            continue

        token_overlap = sum(1 for token in candidate.get("tokens", set()) if token and token in search_text)
        role_bonus = 2 if slide_role and slide_role in candidate.get("role_hints", set()) else 0
        reuse_penalty = min(3, usage_counts.get(short_key, 0))
        total_score = int(candidate.get("base_priority", 0)) + token_overlap + role_bonus - reuse_penalty

        # Require textual evidence for non-method slides; method slides may use role-aligned context.
        if token_overlap == 0 and not (slide_role == "method" and role_bonus > 0):
            continue
        if total_score < 6:
            continue

        scored = dict(candidate)
        scored["_token_overlap"] = token_overlap
        scored["_role_bonus"] = role_bonus

        ranked.append((total_score, scored))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in ranked]


def _infer_reference_citation_purpose(*, slide_role: str, candidate: dict[str, Any]) -> str:
    token_overlap = int(candidate.get("_token_overlap", 0) or 0)
    role_hints = candidate.get("role_hints", set())

    if slide_role == "method":
        return "method_background"
    if slide_role in {"result", "discussion", "limitation"} and token_overlap >= 2:
        return "source_of_claim"
    if "method" in role_hints and slide_role in {"motivation", "problem", "contribution"}:
        return "contextual_reference"
    return "contextual_reference"


def _build_reference_usage_counts(*, slides: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, int]:
    candidate_keys = {
        str(candidate.get("short_citation", "")).strip().lower()
        for candidate in candidates
        if str(candidate.get("short_citation", "")).strip()
    }
    usage_counts = {key: 0 for key in candidate_keys}

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        citations = slide.get("citations", [])
        if not isinstance(citations, list):
            continue
        seen_on_slide: set[str] = set()
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            if str(citation.get("source_kind", "")).strip() != "reference_paper":
                continue
            short_key = str(citation.get("short_citation", "")).strip().lower()
            if short_key in candidate_keys:
                seen_on_slide.add(short_key)
        for key in seen_on_slide:
            usage_counts[key] = usage_counts.get(key, 0) + 1

    return usage_counts


def _match_reference_candidate(search_text: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    et_al_mention = bool(re.search(r"[A-Za-z][A-Za-z'`-]+\s+et\s+al\.?\s*\(?\d{4}\)?", search_text, flags=re.IGNORECASE))
    best_candidate: dict[str, Any] | None = None
    best_score = 0

    for candidate in candidates:
        score = 0
        for token in candidate["tokens"]:
            if token and token in search_text:
                score += 1
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is not None and best_score > 0:
        return best_candidate
    if et_al_mention:
        return candidates[0]
    return None


def _select_reference_context_slide(slides: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred_roles = ["discussion", "method", "result", "conclusion"]
    for role in preferred_roles:
        for slide in slides:
            if isinstance(slide, dict) and str(slide.get("slide_role", "")) == role:
                return slide
    for slide in slides:
        if isinstance(slide, dict) and str(slide.get("slide_role", "")) != "title":
            return slide
    return slides[0] if slides else None


def _apply_notes_repairs(notes: SpeakerNotes, audit_report: AuditReport) -> SpeakerNotes:
    note_slides = {
        audit.slide_number
        for audit in audit_report.slide_audits
        for finding in audit.findings
        if finding.category == "notes_issue"
    }

    payload = notes.model_dump()
    for slide_note in payload["slide_notes"]:
        if slide_note["slide_number"] in note_slides:
            slide_note["talking_points"] = slide_note["talking_points"][:3]
            slide_note["caution_notes"] = slide_note.get("caution_notes", []) + ["Keep claims strictly source-backed."]
    payload["global_notes_warnings"] = payload.get("global_notes_warnings", []) + [
        "Speaker notes trimmed to reduce unsupported elaboration risk."
    ]
    return SpeakerNotes.model_validate(payload)


def _apply_translation_repairs(plan: PresentationPlan, notes: SpeakerNotes) -> tuple[PresentationPlan, SpeakerNotes]:
    plan_payload = plan.model_dump()
    notes_payload = notes.model_dump()
    plan_payload["global_warnings"] = plan_payload.get("global_warnings", []) + [
        "Translation-sensitive wording reviewed in repair cycle."
    ]
    notes_payload["global_notes_warnings"] = notes_payload.get("global_notes_warnings", []) + [
        "Translation tone reviewed for fidelity."
    ]
    return PresentationPlan.model_validate(plan_payload), SpeakerNotes.model_validate(notes_payload)


def _enforce_external_reference_citation_audit_guard(
    *,
    audit_report: AuditReport,
    presentation_plan: PresentationPlan,
) -> AuditReport:
    """Fail audit when external-work mention patterns lack reference-paper citations."""
    payload = audit_report.model_dump()

    slide_audits_raw = payload.get("slide_audits", [])
    if not isinstance(slide_audits_raw, list):
        slide_audits_raw = []
        payload["slide_audits"] = slide_audits_raw

    audit_by_slide: dict[int, dict[str, Any]] = {}
    for item in slide_audits_raw:
        if not isinstance(item, dict):
            continue
        slide_number = int(item.get("slide_number", 0) or 0)
        if slide_number > 0 and slide_number not in audit_by_slide:
            audit_by_slide[slide_number] = item

    flagged_slides: list[int] = []

    for slide in presentation_plan.slides:
        search_blob = _build_slide_search_text(slide.model_dump())
        has_external_mention = bool(
            re.search(r"\b[A-Za-z][A-Za-z'`-]+\s+et\s+al\.?\s*\(?\d{4}\)?", search_blob, flags=re.IGNORECASE)
            or re.search(r"\b[A-Za-z][A-Za-z'`-]+\s*\(\d{4}\)", search_blob)
        )
        if not has_external_mention:
            continue

        has_reference_citation = any(c.source_kind == "reference_paper" for c in slide.citations)
        if has_reference_citation:
            continue

        slide_number = int(slide.slide_number)
        flagged_slides.append(slide_number)

        slide_audit = audit_by_slide.get(slide_number)
        if slide_audit is None:
            slide_audit = {
                "slide_number": slide_number,
                "slide_title": slide.title,
                "overall_support": "supported",
                "findings": [],
                "required_action": "none",
            }
            slide_audits_raw.append(slide_audit)
            audit_by_slide[slide_number] = slide_audit

        findings = slide_audit.get("findings", [])
        if not isinstance(findings, list):
            findings = []
            slide_audit["findings"] = findings

        already_flagged = any(
            isinstance(item, dict)
            and item.get("category") == "citation_issue"
            and "external-work" in str(item.get("description", "")).lower()
            for item in findings
        )
        if already_flagged:
            continue

        findings.append(
            {
                "severity": "high",
                "category": "citation_issue",
                "description": "External-work mention detected without reference_paper citation.",
                "evidence_basis": [
                    {
                        "source_type": "presentation_plan",
                        "source_id": f"slide_{slide_number}",
                        "note": "Slide text includes external-work mention pattern (e.g., et al. + year).",
                    }
                ],
                "recommended_fix": "Add at least one source_kind=reference_paper citation to this slide.",
            }
        )
        slide_audit["overall_support"] = "unsupported"
        slide_audit["required_action"] = "add_citation"

    if not flagged_slides:
        return audit_report

    deck_findings = payload.get("deck_level_findings", [])
    if not isinstance(deck_findings, list):
        deck_findings = []
        payload["deck_level_findings"] = deck_findings

    if not any(
        isinstance(item, dict)
        and item.get("category") == "weak_reference_use"
        and "external-work" in str(item.get("description", "")).lower()
        for item in deck_findings
    ):
        deck_findings.append(
            {
                "severity": "high",
                "category": "weak_reference_use",
                "description": "External-work mentions exist without matching reference-paper citations.",
                "recommended_fix": "Require reference_paper citations for slides mentioning external works.",
            }
        )

    priorities = payload.get("repair_priority", [])
    if not isinstance(priorities, list):
        priorities = []
        payload["repair_priority"] = priorities
    existing_priority_slides = {
        int(item.get("slide_number", 0) or 0)
        for item in priorities
        if isinstance(item, dict)
    }
    current_max_priority = max(
        [int(item.get("priority_order", 0) or 0) for item in priorities if isinstance(item, dict)],
        default=0,
    )
    for slide_number in flagged_slides:
        if slide_number in existing_priority_slides:
            continue
        current_max_priority += 1
        priorities.append(
            {
                "priority_order": current_max_priority,
                "slide_number": slide_number,
                "reason": "Missing reference_paper citation for external-work mention.",
            }
        )

    warnings = payload.get("global_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    guard_warning = (
        "External-reference citation guard: one or more slides mention external works "
        "without reference_paper citations."
    )
    if guard_warning not in warnings:
        warnings.append(guard_warning)
    payload["global_warnings"] = warnings

    payload["deck_risk_level"] = "high"
    payload["audit_status"] = "failed"
    return AuditReport.model_validate(payload)


def _count_unresolved_high(audit_report: AuditReport) -> int:
    return sum(1 for audit in audit_report.slide_audits for finding in audit.findings if finding.severity == "high")


def _build_failed_pptx_result(output_path: Path, error: Exception) -> PPTXBuildResult:
    """Build a structured fallback result when PPTX rendering fails."""
    return PPTXBuildResult.model_validate(
        {
            "build_status": "failed",
            "output": {
                "pptx_path": str(output_path),
                "template_used": "default",
                "notes_insertion_supported": True,
            },
            "slide_build_results": [],
            "global_warnings": [f"PPTX build failed: {error}"],
            "deviations": [
                {
                    "type": "other",
                    "description": f"PPTX render failure: {error}",
                }
            ],
        }
    )


def _copy_pdf_to_run(pdf_path: Path, run_manager: RunManager) -> Path:
    source_path = pdf_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {source_path}")

    target_path = run_manager.get_run_path() / "source_paper" / source_path.name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return target_path


def _persist_pdf_artifacts(
    run_manager: RunManager,
    pdf_parse_output: PDFParseOutput,
    section_candidates: list[SectionCandidate],
) -> None:
    run_manager.save_text("analysis/full_text.txt", pdf_parse_output.combined_text)
    run_manager.save_json(
        "analysis/pdf_parse_output.json",
        {
            "pdf_path": str(pdf_parse_output.pdf_path),
            "page_count": pdf_parse_output.page_count,
            "warnings": pdf_parse_output.warnings,
            "page_texts": pdf_parse_output.page_texts,
        },
    )

    serialized_sections = []
    for idx, candidate in enumerate(section_candidates, start=1):
        section_path = run_manager.save_text(f"analysis/sections/section_{idx:02d}.txt", candidate.text)
        serialized_sections.append(
            {
                "section_title": candidate.section_title,
                "start_index": candidate.start_index,
                "end_index": candidate.end_index,
                "confidence": candidate.confidence,
                "inferred": candidate.inferred,
                "text_path": str(section_path),
            }
        )
    run_manager.save_json("analysis/section_candidates.json", {"sections": serialized_sections})


def _build_retrieval_candidates(
    references_raw: list[str],
    arxiv_client: ArxivClient | None,
) -> list[dict[str, Any]]:
    candidates = []
    for item in references_raw:
        search_results: list[dict[str, Any]] = []
        search_queries = _build_arxiv_search_queries(item)
        extracted_id = ArxivClient.extract_arxiv_id(item)
        if extracted_id:
            search_results.append(
                {
                    "title": "",
                    "authors": [],
                    "year": "",
                    "source": "arxiv",
                    "url": f"https://arxiv.org/abs/{extracted_id}",
                    "pdf_url": f"https://arxiv.org/pdf/{extracted_id}.pdf",
                    "arxiv_id": extracted_id,
                }
            )
            if arxiv_client is not None:
                by_id = arxiv_client.get_by_id(extracted_id)
                if by_id is not None:
                    search_results.insert(0, by_id)
        elif arxiv_client is not None:
            for query in search_queries[:_ARXIV_QUERY_MAX_ATTEMPTS]:
                query_results = arxiv_client.search(query, max_results=2)
                for record in query_results:
                    if _is_duplicate_arxiv_candidate(existing=search_results, candidate=record):
                        continue
                    search_results.append(record)
                    if len(search_results) >= _ARXIV_QUERY_MAX_CANDIDATES:
                        break
                if len(search_results) >= _ARXIV_QUERY_MAX_CANDIDATES:
                    break

        # Fallback provider: enrich candidate pool via OpenAlex title search.
        if not search_results:
            openalex_candidates = _build_openalex_search_candidates(
                search_queries=search_queries,
            )
            for record in openalex_candidates:
                if _is_duplicate_arxiv_candidate(existing=search_results, candidate=record):
                    continue
                search_results.append(record)
                if len(search_results) >= _ARXIV_QUERY_MAX_CANDIDATES:
                    break
        candidates.append({"reference_text": item, "arxiv_candidates": search_results})
    return candidates


def _build_openalex_search_candidates(*, search_queries: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for query in search_queries[:_OPENALEX_QUERY_MAX_ATTEMPTS]:
        encoded_query = urllib.parse.quote(str(query or "").strip())
        if not encoded_query:
            continue

        payload = _fetch_openalex_json(
            f"https://api.openalex.org/works?search={encoded_query}&per-page=5"
        )
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(results, list):
            continue

        for result in results:
            if not isinstance(result, dict):
                continue

            title = str(result.get("display_name", "") or "").strip()
            if not title:
                continue

            authors: list[str] = []
            authorships = result.get("authorships", [])
            if isinstance(authorships, list):
                for item in authorships:
                    if not isinstance(item, dict):
                        continue
                    author_blob = item.get("author", {})
                    if not isinstance(author_blob, dict):
                        continue
                    name = str(author_blob.get("display_name", "") or "").strip()
                    if name:
                        authors.append(name)

            year = str(result.get("publication_year", "") or "")
            doi_value = _extract_doi(str(result.get("doi", "") or ""))
            source_url = f"https://doi.org/{doi_value}" if doi_value else str(result.get("id", "") or "")
            pdf_url = _extract_pdf_url_from_openalex(result)
            arxiv_id = ArxivClient.extract_arxiv_id(source_url) or ArxivClient.extract_arxiv_id(pdf_url)

            source = "web"
            if doi_value:
                source = "doi"
            elif arxiv_id:
                source = "arxiv"

            candidates.append(
                {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "source": source,
                    "url": source_url,
                    "pdf_url": pdf_url,
                    "arxiv_id": arxiv_id,
                }
            )

            if len(candidates) >= _OPENALEX_QUERY_MAX_CANDIDATES:
                return candidates

    return candidates


def _build_arxiv_search_queries(reference_text: str) -> list[str]:
    """Generate normalized arXiv query variants from a reference string."""
    normalized_reference = _SPLIT_REFERENCE_PREFIX.sub("", str(reference_text or "").strip())
    inferred = _infer_reference_metadata(normalized_reference)

    extracted_title = _extract_title_sentence_for_search(normalized_reference)
    title = extracted_title or str(inferred.get("title", "") or "").strip()
    title = re.sub(r"\s+", " ", title).strip(" ,.;")
    year = str(inferred.get("year", "") or "").strip()
    authors = inferred.get("authors", [])
    if not isinstance(authors, list):
        authors = []

    lead_author = ""
    if authors:
        lead_author = str(authors[0]).strip()
    lead_surname = lead_author.split()[-1] if lead_author else ""

    queries: list[str] = []

    if title:
        queries.append(title)
    if title and lead_author:
        queries.append(f"{title} {lead_author}")
    if title and lead_surname:
        queries.append(f"{title} {lead_surname}")
    if title and year:
        queries.append(f"{title} {year}")

    # Keep a short raw fallback as a final query for uncommon formats.
    short_reference = re.sub(r"\s+", " ", normalized_reference).strip()
    if short_reference:
        queries.append(short_reference[:180])

    deduped_queries: list[str] = []
    seen_queries: set[str] = set()
    for query in queries:
        cleaned_query = str(query or "").strip()
        if not cleaned_query:
            continue
        key = cleaned_query.lower()
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped_queries.append(cleaned_query)

    return deduped_queries


def _extract_title_sentence_for_search(reference_text: str) -> str:
    """Extract a plausible title segment from citation prose for search queries."""
    text = re.sub(r"\s+", " ", str(reference_text or "").strip())
    if not text:
        return ""

    raw_parts = [part.strip(" ,.;") for part in re.split(r"\.\s+", text) if part.strip(" ,.;")]
    if not raw_parts:
        return ""

    for part in raw_parts:
        if len(part.split()) < 3:
            continue
        if _looks_like_author_segment(part):
            continue

        lowered = part.lower()
        if lowered.startswith("in ") or lowered.startswith("proceedings"):
            continue
        if "arxiv" in lowered or lowered.startswith("corr"):
            continue
        return part

    return ""


def _is_duplicate_arxiv_candidate(*, existing: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_id = ArxivClient.extract_arxiv_id(str(candidate.get("arxiv_id", "") or candidate.get("url", "")))
    candidate_url = str(candidate.get("url", "") or "").strip().lower()

    for record in existing:
        existing_id = ArxivClient.extract_arxiv_id(str(record.get("arxiv_id", "") or record.get("url", "")))
        if candidate_id and existing_id and candidate_id == existing_id:
            return True

        existing_url = str(record.get("url", "") or "").strip().lower()
        if candidate_url and existing_url and candidate_url == existing_url:
            return True

    return False


def _run_reference_retrieval_with_batches(
    *,
    reference_retrieval_agent: ReferenceRetrievalAgent,
    stage_entry: dict[str, Any],
    job_spec_payload: dict[str, Any],
    source_metadata_payload: dict[str, Any],
    references_raw: list[str],
    reference_parse_warnings: list[str],
    retrieval_candidates: list[dict[str, Any]],
    enable_batching: bool = True,
) -> ReferenceIndex:
    """Run A4 retrieval in chunks for long bibliographies and merge the results."""
    total_references = len(references_raw)
    if not enable_batching or total_references <= _A4_BATCH_TRIGGER_COUNT:
        return reference_retrieval_agent.run(
            {
                "job_spec": job_spec_payload,
                "source_metadata": source_metadata_payload,
                "references_raw": references_raw,
                "reference_parse_warnings": reference_parse_warnings,
                "retrieval_candidates": retrieval_candidates,
            }
        )

    merged_entries: list[dict[str, Any]] = []
    merged_warnings: list[str] = [
        f"A4 batched retrieval enabled for {total_references} references (batch_size={_A4_BATCH_SIZE})."
    ]
    batch_failures: list[str] = []

    for batch_start in range(0, total_references, _A4_BATCH_SIZE):
        batch_end = min(total_references, batch_start + _A4_BATCH_SIZE)
        batch_index = (batch_start // _A4_BATCH_SIZE) + 1
        batch_references = references_raw[batch_start:batch_end]
        batch_candidates = retrieval_candidates[batch_start:batch_end] if retrieval_candidates else []

        try:
            batch_result = reference_retrieval_agent.run(
                {
                    "job_spec": job_spec_payload,
                    "source_metadata": source_metadata_payload,
                    "references_raw": batch_references,
                    "reference_parse_warnings": reference_parse_warnings,
                    "retrieval_candidates": batch_candidates,
                }
            )
        except Exception as exc:
            batch_failures.append(
                f"A4 batch {batch_index} ({batch_start + 1}-{batch_end}) failed: {exc}"
            )
            continue

        batch_payload = batch_result.model_dump()
        batch_entries = batch_payload.get("reference_index", [])
        if not isinstance(batch_entries, list):
            continue

        for offset, raw_entry in enumerate(batch_entries):
            if not isinstance(raw_entry, dict):
                continue
            merged_entry = dict(raw_entry)
            global_position = batch_start + offset + 1
            merged_entry["reference_id"] = f"R{global_position:03d}"
            if not str(merged_entry.get("original_reference_text", "")).strip():
                merged_entry["original_reference_text"] = str(references_raw[global_position - 1])
            merged_entries.append(merged_entry)

        summary = batch_payload.get("retrieval_summary", {})
        if isinstance(summary, dict):
            batch_warnings = summary.get("warnings", [])
            if isinstance(batch_warnings, list):
                merged_warnings.extend(str(item) for item in batch_warnings if str(item).strip())

    merged_warnings.extend(batch_failures)
    stage_warnings = stage_entry.get("warnings", [])
    if not isinstance(stage_warnings, list):
        stage_warnings = []
    stage_warnings.extend(batch_failures)
    stage_entry["warnings"] = stage_warnings

    payload: dict[str, Any] = {
        "reference_index": merged_entries,
        "retrieval_summary": {
            "total_references": 0,
            "retrieved_count": 0,
            "ambiguous_count": 0,
            "not_found_count": 0,
            "warnings": [],
        },
    }
    _recompute_reference_summary(payload=payload, additional_warnings=merged_warnings)
    return ReferenceIndex.model_validate(payload)


def _promote_reference_retrieval_from_identifiers(
    *,
    reference_index: ReferenceIndex,
    arxiv_client: ArxivClient | None,
) -> tuple[ReferenceIndex, list[str]]:
    """Promote not_found entries to retrieved when reliable IDs are present."""
    payload = reference_index.model_dump()
    entries = payload.get("reference_index", [])
    if not isinstance(entries, list):
        return reference_index, []

    promoted_ids: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("retrieval_status", "")).strip() == "retrieved":
            continue

        parsed = entry.get("parsed_reference", {})
        if not isinstance(parsed, dict):
            continue

        arxiv_id = ArxivClient.extract_arxiv_id(str(parsed.get("arxiv_id", "")))
        if not arxiv_id:
            continue

        matched_record = entry.get("matched_record", {})
        if not isinstance(matched_record, dict):
            matched_record = {}
            entry["matched_record"] = matched_record

        record = arxiv_client.get_by_id(arxiv_id) if arxiv_client is not None else None
        if record is not None:
            matched_record["title"] = str(record.get("title", "") or str(parsed.get("title", "") or ""))
            matched_record["authors"] = list(record.get("authors", []))
            matched_record["year"] = str(record.get("year", "") or str(parsed.get("year", "") or ""))
            matched_record["url"] = str(record.get("url", "") or f"https://arxiv.org/abs/{arxiv_id}")
            matched_record["source"] = "arxiv"
        else:
            matched_record["title"] = str(parsed.get("title", "") or "")
            matched_record["authors"] = list(parsed.get("authors", [])) if isinstance(parsed.get("authors", []), list) else []
            matched_record["year"] = str(parsed.get("year", "") or "")
            matched_record["url"] = str(matched_record.get("url", "") or f"https://arxiv.org/abs/{arxiv_id}")
            matched_record["source"] = "arxiv"

        matched_record.setdefault("pdf_path", "")
        matched_record.setdefault("reference_folder_path", "")

        entry["retrieval_status"] = "retrieved"
        entry["match_confidence"] = "medium"
        entry["failure_reason"] = ""
        promoted_ids.append(str(entry.get("reference_id", "")).strip() or "unknown")

    warnings: list[str] = []
    if promoted_ids:
        warnings.append(
            "Promoted reference retrieval from parsed arXiv IDs: " + ", ".join(promoted_ids)
        )

    _recompute_reference_summary(payload=payload, additional_warnings=warnings)
    return ReferenceIndex.model_validate(payload), warnings


def _enforce_reference_retrieval_integrity(
    *,
    reference_index: ReferenceIndex,
    run_path: Path,
    arxiv_client: ArxivClient | None,
) -> tuple[ReferenceIndex, list[str]]:
    """Verify that each retrieved reference has a physical PDF artifact.

    Any "retrieved" record without a verifiable local PDF is downgraded to "not_found".
    """
    payload = reference_index.model_dump()
    warnings: list[str] = []
    entries = payload.get("reference_index", [])
    if not isinstance(entries, list):
        return reference_index, warnings

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("retrieval_status", "")) != "retrieved":
            continue

        matched_record = entry.get("matched_record", {})
        if not isinstance(matched_record, dict):
            matched_record = {}
            entry["matched_record"] = matched_record

        reference_id = str(entry.get("reference_id", "")).strip() or "unknown"
        reference_folder = run_path / "references" / reference_id
        reference_folder.mkdir(parents=True, exist_ok=True)

        existing_pdf = _resolve_existing_reference_pdf(
            matched_record.get("pdf_path", ""),
            run_path,
        )
        if existing_pdf is None:
            existing_pdf = _download_reference_pdf_if_possible(
                entry=entry,
                matched_record=matched_record,
                reference_folder=reference_folder,
                arxiv_client=arxiv_client,
            )

        if existing_pdf is None:
            entry["retrieval_status"] = "not_found"
            entry["match_confidence"] = "low"
            if not str(entry.get("failure_reason", "")).strip():
                entry["failure_reason"] = "Retrieved candidate could not be verified: local PDF artifact is missing."
            matched_record["pdf_path"] = ""
            matched_record["reference_folder_path"] = ""
            warnings.append(f"{reference_id}: downgraded retrieved -> not_found because no PDF file was present.")
            continue

        matched_record["pdf_path"] = str(existing_pdf)
        matched_record["reference_folder_path"] = str(reference_folder)

    _recompute_reference_summary(payload=payload, additional_warnings=warnings)

    return ReferenceIndex.model_validate(payload), warnings


def _recover_references_deterministically(
    *,
    reference_index: ReferenceIndex,
    run_path: Path,
    arxiv_client: ArxivClient | None,
) -> tuple[ReferenceIndex, list[str]]:
    """Attempt deterministic retrieval/download for entries A4 left unresolved."""
    payload = reference_index.model_dump()
    entries = payload.get("reference_index", [])
    if not isinstance(entries, list):
        return reference_index, []

    recovered_ids: list[str] = []
    attempted_count = 0

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("retrieval_status", "")).strip() == "retrieved":
            continue

        attempted_count += 1
        reference_id = str(entry.get("reference_id", "")).strip() or "unknown"
        reference_folder = run_path / "references" / reference_id
        reference_folder.mkdir(parents=True, exist_ok=True)

        matched_record = entry.get("matched_record", {})
        if not isinstance(matched_record, dict):
            matched_record = {}
            entry["matched_record"] = matched_record

        downloaded_pdf = _download_reference_pdf_if_possible(
            entry=entry,
            matched_record=matched_record,
            reference_folder=reference_folder,
            arxiv_client=arxiv_client,
        )
        if downloaded_pdf is None:
            continue

        matched_record["pdf_path"] = str(downloaded_pdf)
        matched_record["reference_folder_path"] = str(reference_folder)
        entry["retrieval_status"] = "retrieved"
        entry["match_confidence"] = "medium"
        entry["failure_reason"] = ""
        recovered_ids.append(reference_id)

    warnings: list[str] = []
    if recovered_ids:
        warnings.append(
            "Deterministic retrieval recovered references not returned by A4: " + ", ".join(recovered_ids)
        )
    if attempted_count:
        warnings.append(
            f"Deterministic retrieval attempted {attempted_count} unresolved references after A4."
        )

    _recompute_reference_summary(payload=payload, additional_warnings=warnings)
    return ReferenceIndex.model_validate(payload), warnings


def _ensure_reference_index_coverage(
    *,
    reference_index: ReferenceIndex,
    references_raw: list[str],
) -> tuple[ReferenceIndex, list[str]]:
    """Ensure A4 output contains one entry per parsed raw reference (in order)."""
    payload = reference_index.model_dump()
    entries = payload.get("reference_index", [])
    warnings: list[str] = []

    if not isinstance(entries, list):
        entries = []
    if not references_raw:
        _recompute_reference_summary(payload=payload, additional_warnings=[])
        return ReferenceIndex.model_validate(payload), warnings

    by_id: dict[str, dict[str, Any]] = {}
    by_text: dict[str, list[dict[str, Any]]] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        rid = str(raw_entry.get("reference_id", "")).strip()
        if rid and rid not in by_id:
            by_id[rid] = raw_entry

        original_text = str(raw_entry.get("original_reference_text", "")).strip()
        if original_text:
            by_text.setdefault(original_text, []).append(raw_entry)

    used_source_entry_ids: set[int] = set()
    rebuilt_entries: list[dict[str, Any]] = []

    for idx, raw_ref in enumerate(references_raw, start=1):
        expected_id = f"R{idx:03d}"
        reference_text = str(raw_ref or "").strip()

        selected = by_id.get(expected_id)
        if selected is not None and id(selected) in used_source_entry_ids:
            selected = None

        if selected is None and reference_text:
            for candidate in by_text.get(reference_text, []):
                if id(candidate) not in used_source_entry_ids:
                    selected = candidate
                    break

        if selected is None:
            selected = _build_missing_reference_entry(expected_id, reference_text)
            warnings.append(f"{expected_id}: synthesized missing A4 entry to preserve reference coverage.")
        else:
            used_source_entry_ids.add(id(selected))
            selected = dict(selected)

        selected["reference_id"] = expected_id
        if not str(selected.get("original_reference_text", "")).strip():
            selected["original_reference_text"] = reference_text

        selected = _backfill_reference_parsed_fields(entry=selected, reference_text=reference_text)
        rebuilt_entries.append(selected)

    payload["reference_index"] = rebuilt_entries
    _recompute_reference_summary(payload=payload, additional_warnings=warnings)
    return ReferenceIndex.model_validate(payload), warnings


def _build_missing_reference_entry(reference_id: str, reference_text: str) -> dict[str, Any]:
    inferred = _infer_reference_metadata(reference_text)
    parsing_confidence = "low"
    if inferred["authors"] and inferred["year"]:
        parsing_confidence = "medium"
    elif inferred["authors"] or inferred["year"] or inferred["title"]:
        parsing_confidence = "medium"

    return {
        "reference_id": reference_id,
        "original_reference_text": reference_text,
        "parsed_reference": {
            "title": inferred["title"],
            "authors": inferred["authors"],
            "venue_or_source": inferred["venue_or_source"],
            "year": inferred["year"],
            "arxiv_id": inferred["arxiv_id"],
            "doi": inferred["doi"],
        },
        "parsing_confidence": parsing_confidence,
        "retrieval_status": "not_found",
        "matched_record": {
            "title": "",
            "authors": [],
            "year": "",
            "source": "other",
            "url": "",
            "pdf_path": "",
            "reference_folder_path": "",
        },
        "match_confidence": "low",
        "alternative_candidates": [],
        "failure_reason": "Missing from A4 model output; synthesized by deterministic coverage guard.",
        "notes": [],
    }


def _backfill_reference_parsed_fields(*, entry: dict[str, Any], reference_text: str) -> dict[str, Any]:
    """Fill missing parsed reference metadata from raw text when A4 output is incomplete."""
    enriched = dict(entry)
    parsed = enriched.get("parsed_reference", {})
    if not isinstance(parsed, dict):
        parsed = {}
    parsed = dict(parsed)

    inferred = _infer_reference_metadata(reference_text)

    title = str(parsed.get("title", "") or "").strip()
    authors = parsed.get("authors", [])
    if not isinstance(authors, list):
        authors = [] if authors is None or str(authors).strip() == "" else [str(authors)]
    authors = [str(item).strip() for item in authors if str(item).strip()]
    year = str(parsed.get("year", "") or "").strip()
    venue_or_source = str(parsed.get("venue_or_source", "") or "").strip()
    arxiv_id = str(parsed.get("arxiv_id", "") or "").strip()
    doi = str(parsed.get("doi", "") or "").strip()

    if not title or title.lower() == str(reference_text or "").strip().lower():
        title = inferred["title"]
    if not authors and inferred["authors"]:
        authors = inferred["authors"]
    if not year and inferred["year"]:
        year = inferred["year"]
    if not venue_or_source and inferred["venue_or_source"]:
        venue_or_source = inferred["venue_or_source"]
    if not arxiv_id and inferred["arxiv_id"]:
        arxiv_id = inferred["arxiv_id"]
    if not doi and inferred["doi"]:
        doi = inferred["doi"]

    authors = _normalize_reference_author_list(authors)

    parsed.update(
        {
            "title": title,
            "authors": authors,
            "venue_or_source": venue_or_source,
            "year": year,
            "arxiv_id": arxiv_id,
            "doi": doi,
        }
    )
    enriched["parsed_reference"] = parsed

    parsing_confidence = str(enriched.get("parsing_confidence", "low") or "low")
    if parsing_confidence == "low" and (title or authors or year):
        enriched["parsing_confidence"] = "medium"

    return enriched


def _infer_reference_title(reference_text: str) -> str:
    text = str(reference_text or "").strip()
    if not text:
        return ""

    quote_match = re.search(r"[\"“](.+?)[\"”]", text)
    if quote_match:
        return quote_match.group(1).strip().rstrip(" ,.;")

    cleaned = _SPLIT_REFERENCE_PREFIX.sub("", text)
    candidate = cleaned

    if "." in cleaned:
        first_part, rest = cleaned.split(".", 1)
        if rest.strip() and _looks_like_author_segment(first_part):
            candidate = rest.strip()

    year_match = _YEAR_PATTERN.search(candidate)
    if year_match:
        candidate = candidate[: year_match.start()].rstrip(" ,.;")

    segment = candidate.split(".", 1)[0].strip()
    if not segment:
        segment = text.split(".", 1)[0].strip()
    return segment[:120].rstrip(" ,.;")


def _infer_reference_metadata(reference_text: str) -> dict[str, Any]:
    text = _SPLIT_REFERENCE_PREFIX.sub("", str(reference_text or "").strip())
    year = ""
    year_match = _YEAR_PATTERN.search(text)
    if year_match:
        year = year_match.group(0)

    title = _infer_reference_title(text)
    arxiv_id = ArxivClient.extract_arxiv_id(text)
    doi = _extract_doi(text)
    authors = _infer_reference_authors(text=text, title=title, year=year)

    return {
        "title": title,
        "authors": authors,
        "venue_or_source": "",
        "year": year,
        "arxiv_id": arxiv_id,
        "doi": doi,
    }


def _infer_reference_authors(*, text: str, title: str, year: str) -> list[str]:
    if not text:
        return []

    normalized_text = _SPLIT_REFERENCE_PREFIX.sub("", text)

    boundary = len(text)
    quoted_title_match = re.search(r"[\"“](.+?)[\"”]", normalized_text)
    if quoted_title_match:
        boundary = min(boundary, quoted_title_match.start())
    elif title:
        title_index = normalized_text.lower().find(title.lower())
        if title_index > 0:
            boundary = min(boundary, title_index)

    if year:
        year_index = normalized_text.find(year)
        if year_index > 0:
            boundary = min(boundary, year_index)

    author_segment = normalized_text[:boundary].strip(" ,.;")
    if not author_segment:
        return []

    normalized = re.sub(r"\bet\s+al\.?", "", author_segment, flags=re.IGNORECASE)
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,.;")
    if not normalized:
        return []

    surname_first_preferred = False
    first_comma_left = normalized.split(",", 1)[0].strip() if "," in normalized else ""
    if first_comma_left and len(first_comma_left.split()) == 1:
        surname_first_preferred = True

    surname_first_matches = re.findall(
        r"([A-Z][A-Za-z'`-]{1,30})\s*,\s*([A-Z][A-Za-z'`.-]+(?:\s+[A-Z][A-Za-z'`.-]+){0,3})",
        normalized,
    )
    if surname_first_matches and surname_first_preferred:
        deduped: list[str] = []
        seen: set[str] = set()
        for surname, given_names in surname_first_matches:
            full_name = f"{given_names.strip()} {surname.strip()}".strip()
            key = full_name.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(full_name)
            if len(deduped) >= 8:
                break

        trailing_name_matches = re.findall(
            r"(?:\band\b|,)\s*([A-Z][A-Za-z'`.-]+(?:\s+[A-Z][A-Za-z'`.-]+){1,3})",
            normalized,
        )
        for candidate in trailing_name_matches:
            full_name = candidate.strip(" ,.;")
            if not full_name:
                continue
            key = full_name.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(full_name)
            if len(deduped) >= 8:
                break

        return _normalize_reference_author_list(deduped)

    parts = re.split(r"\s*(?:,| and )\s*", normalized)
    deduped = []
    seen = set()
    for part in parts:
        candidate = part.strip(" ,.;")
        if not candidate:
            continue
        words = candidate.split()
        if len(words) < 2:
            continue
        if not any(word[0].isupper() for word in words if word):
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= 8:
            break

    return _normalize_reference_author_list(deduped)


def _split_author_candidates(author_segment: str) -> list[str]:
    text = str(author_segment or "").strip()
    if not text:
        return []
    text = text.replace("&", " and ")
    text = re.sub(r"\bet\s+al\.?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,.;")
    if not text:
        return []

    if "," in text and " and " in text:
        text = text.replace(" and ", ", ")
    parts = [item.strip(" ,.;") for item in text.split(",")]
    return [item for item in parts if item]


def _looks_like_author_segment(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if any(token in text.lower() for token in ["arxiv", "corr", "proceedings", "journal", "conference", "pages"]):
        return False
    words = [item for item in re.split(r"\s+", text) if item]
    if len(words) < 2:
        return False
    capitalized = sum(1 for word in words if word and word[0].isupper())
    return capitalized >= 2


def _normalize_reference_author_list(authors: list[str]) -> list[str]:
    """Normalize author list and drop obvious merged/composite candidates."""
    cleaned: list[str] = []
    seen: set[str] = set()

    for raw in authors:
        text = str(raw or "").strip(" ,.;")
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        if any(ch.isdigit() for ch in text):
            continue
        words = text.split()
        if len(words) < 2 or len(words) > 6:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

    if len(cleaned) <= 1:
        return cleaned

    surnames = [name.split()[-1].lower() for name in cleaned if name.split()]
    surname_set = set(surnames)
    surname_counts: dict[str, int] = {}
    for surname in surnames:
        surname_counts[surname] = surname_counts.get(surname, 0) + 1

    normalized: list[str] = []
    for name in cleaned:
        parts = name.split()
        lower_parts = [item.lower() for item in parts]
        last = lower_parts[-1]

        # Drop entries that look like two authors fused together, e.g.
        # "Kevin K. Troy Belonax" when both "Kevin K. Troy" and "Tim Belonax"
        # also appear in the same candidate set.
        if len(parts) >= 3:
            inner_surnames = {token for token in lower_parts[1:-1] if token in surname_set}
            if surname_counts.get(last, 0) > 1 and inner_surnames:
                continue

        normalized.append(name)

    return normalized


def _format_unresolved_reference_citation_label(short_citation: str) -> str:
    text = str(short_citation or "").strip()
    if not text:
        return "Reference unresolved"

    match = _REFERENCE_ID_PATTERN.search(text)
    if not match:
        return "Reference unresolved"

    reference_id = match.group(0).upper()
    return f"Reference {reference_id} unresolved"


def _recompute_reference_summary(*, payload: dict[str, Any], additional_warnings: list[str]) -> None:
    entries = payload.get("reference_index", [])
    if not isinstance(entries, list):
        entries = []

    status_counts = {
        "retrieved": 0,
        "ambiguous_match": 0,
        "not_found": 0,
        "skipped": 0,
    }
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("retrieval_status", ""))
        if status in status_counts:
            status_counts[status] += 1

    summary = payload.get("retrieval_summary", {})
    if not isinstance(summary, dict):
        summary = {}
    existing_warnings = summary.get("warnings", [])
    if not isinstance(existing_warnings, list):
        existing_warnings = []

    summary.update(
        {
            "total_references": len(entries),
            "retrieved_count": status_counts["retrieved"],
            "ambiguous_count": status_counts["ambiguous_match"],
            "not_found_count": status_counts["not_found"],
            "warnings": [*existing_warnings, *additional_warnings],
        }
    )
    payload["retrieval_summary"] = summary


def _resolve_existing_reference_pdf(pdf_path: str, run_path: Path) -> Path | None:
    raw_path = str(pdf_path or "").strip()
    if not raw_path:
        return None

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (run_path / candidate).resolve()

    if not candidate.is_file():
        return None
    if candidate.suffix.lower() != ".pdf":
        return None
    return candidate


def _download_reference_pdf_if_possible(
    *,
    entry: dict[str, Any],
    matched_record: dict[str, Any],
    reference_folder: Path,
    arxiv_client: ArxivClient | None,
) -> Path | None:
    parsed_reference = entry.get("parsed_reference", {})
    parsed_arxiv_id = ""
    if isinstance(parsed_reference, dict):
        parsed_arxiv_id = ArxivClient.extract_arxiv_id(str(parsed_reference.get("arxiv_id", "")))

    matched_url = str(matched_record.get("url", ""))
    matched_arxiv_id = ArxivClient.extract_arxiv_id(matched_url)
    candidate_arxiv_id = parsed_arxiv_id or matched_arxiv_id

    record: dict[str, Any] | None = None
    if candidate_arxiv_id and arxiv_client is not None:
        record = arxiv_client.get_by_id(candidate_arxiv_id)

    if record is None and arxiv_client is not None:
        title_query = ""
        if isinstance(parsed_reference, dict):
            title_query = str(parsed_reference.get("title", "")).strip()
        if not title_query:
            title_query = str(entry.get("original_reference_text", "")).strip()
        search_candidates = arxiv_client.search(title_query, max_results=1)
        if search_candidates:
            record = search_candidates[0]

    if record is None and candidate_arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{candidate_arxiv_id}.pdf"
        resolved_source = "arxiv"
        resolved_url = f"https://arxiv.org/abs/{candidate_arxiv_id}"
    elif record is None:
        pdf_url = ""
        resolved_source = ""
        resolved_url = ""
    else:
        pdf_url = str(record.get("pdf_url", "")).strip()
        if not pdf_url:
            arxiv_id = arxiv_client.extract_arxiv_id(str(record.get("arxiv_id", "")) or str(record.get("url", "")))
            if arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        resolved_source = str(record.get("source", "arxiv") or "arxiv")
        resolved_url = str(record.get("url", ""))

    if not pdf_url:
        parsed_doi = _extract_doi(
            str(parsed_reference.get("doi", "")) if isinstance(parsed_reference, dict) else ""
        )
        matched_doi = _extract_doi(str(matched_record.get("url", "")))
        reference_doi = _extract_doi(str(entry.get("original_reference_text", "")))
        candidate_doi = parsed_doi or matched_doi or reference_doi

        title_query = ""
        if isinstance(parsed_reference, dict):
            title_query = str(parsed_reference.get("title", "")).strip()
        if not title_query:
            title_query = str(entry.get("original_reference_text", "")).strip()

        oa_pdf_url, oa_source, oa_url = _lookup_open_access_pdf(
            doi=candidate_doi,
            title_query=title_query,
        )
        if oa_pdf_url:
            pdf_url = oa_pdf_url
            resolved_source = oa_source or "web"
            resolved_url = oa_url or resolved_url

    if not pdf_url:
        return None

    arxiv_id = arxiv_client.extract_arxiv_id(str(record.get("arxiv_id", "")) or str(record.get("url", ""))) if record else ""
    file_stem = arxiv_id or (_sanitize_for_filename(_extract_doi(resolved_url)) if resolved_url else "") or str(entry.get("reference_id", "reference"))
    target_path = reference_folder / f"{file_stem}.pdf"

    downloaded_path = _download_pdf_file(pdf_url=pdf_url, target_path=target_path)
    if downloaded_path is None:
        return None

    if record is not None:
        matched_record["title"] = str(record.get("title", matched_record.get("title", "")))
        matched_record["authors"] = list(record.get("authors", matched_record.get("authors", [])))
        matched_record["year"] = str(record.get("year", matched_record.get("year", "")))

    matched_record["source"] = resolved_source or str(matched_record.get("source", "other") or "other")
    if resolved_url:
        matched_record["url"] = resolved_url
    return downloaded_path


def _download_pdf_file(*, pdf_url: str, target_path: Path) -> Path | None:
    try:
        urllib.request.urlretrieve(pdf_url, target_path)
    except Exception:
        return None

    if not target_path.is_file() or target_path.stat().st_size == 0:
        return None
    if target_path.suffix.lower() != ".pdf":
        return None
    return target_path


def _lookup_open_access_pdf(*, doi: str, title_query: str) -> tuple[str | None, str | None, str | None]:
    normalized_doi = _extract_doi(doi)
    if normalized_doi:
        encoded_doi = urllib.parse.quote(f"https://doi.org/{normalized_doi}", safe="")
        work_payload = _fetch_openalex_json(f"https://api.openalex.org/works/{encoded_doi}")
        pdf_url = _extract_pdf_url_from_openalex(work_payload)
        if pdf_url:
            return pdf_url, "doi", f"https://doi.org/{normalized_doi}"

    cleaned_title = (title_query or "").strip()
    if not cleaned_title:
        return None, None, None

    search_query = urllib.parse.quote(cleaned_title)
    search_payload = _fetch_openalex_json(f"https://api.openalex.org/works?search={search_query}&per-page=3")
    results = search_payload.get("results", []) if isinstance(search_payload, dict) else []
    if not isinstance(results, list) or not results:
        return None, None, None

    first = results[0] if isinstance(results[0], dict) else None
    if not first:
        return None, None, None

    pdf_url = _extract_pdf_url_from_openalex(first)
    if not pdf_url:
        return None, None, None

    landing = str(first.get("id", "") or "")
    source = "web"
    doi_value = str(first.get("doi", "") or "")
    if doi_value:
        source = "doi"
        landing = doi_value
    return pdf_url, source, landing


def _fetch_openalex_json(url: str) -> dict[str, Any] | None:
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=12) as response:
                raw = response.read()
        except Exception:
            continue

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload

    return None


def _extract_pdf_url_from_openalex(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""

    open_access = payload.get("open_access", {})
    if isinstance(open_access, dict):
        oa_url = str(open_access.get("oa_url", "") or "").strip()
        if oa_url.lower().endswith(".pdf"):
            return oa_url

    primary_location = payload.get("primary_location", {})
    if isinstance(primary_location, dict):
        pdf_url = str(primary_location.get("pdf_url", "") or "").strip()
        if pdf_url:
            return pdf_url

    locations = payload.get("locations", [])
    if isinstance(locations, list):
        for item in locations:
            if not isinstance(item, dict):
                continue
            pdf_url = str(item.get("pdf_url", "") or "").strip()
            if pdf_url:
                return pdf_url
            source = item.get("source", {})
            if isinstance(source, dict):
                host = str(source.get("host_organization_name", "") or "")
                if "arxiv" in host.lower():
                    landing = str(item.get("landing_page_url", "") or "")
                    arxiv_id = ArxivClient.extract_arxiv_id(landing)
                    if arxiv_id:
                        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return ""


def _extract_doi(text: str | None) -> str:
    if not text:
        return ""
    match = _DOI_PATTERN.search(str(text))
    if not match:
        return ""
    return match.group(1).rstrip(".,;)").lower()


def _sanitize_for_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value or "").strip("._-")
    return cleaned or "reference"


def _select_sections_for_analysis(
    *,
    full_text: str,
    parsed_section_titles: list[str],
    fallback_candidates: list[SectionCandidate],
) -> list[SectionCandidate]:
    """Build section analysis windows using A1 section titles when possible."""
    normalized_text = full_text or ""
    if not normalized_text.strip():
        return fallback_candidates[: max(1, min(3, len(fallback_candidates)))]

    ignored_titles = {"references", "appendix", "acknowledgments", "acknowledgements"}
    title_positions: list[tuple[str, int]] = []
    search_start = 0

    for raw_title in parsed_section_titles:
        title = (raw_title or "").strip()
        if not title:
            continue
        if title.lower() in ignored_titles:
            continue

        heading_pattern = re.compile(
            rf"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*{re.escape(title)}\s*$",
        )
        match = heading_pattern.search(normalized_text, search_start)
        if match is None:
            continue

        title_positions.append((title, match.start()))
        search_start = match.end()

    if not title_positions:
        filtered_fallback = [
            item for item in fallback_candidates if item.section_title.strip().lower() not in ignored_titles
        ]
        if filtered_fallback:
            return filtered_fallback[: max(1, min(3, len(filtered_fallback)))]
        return fallback_candidates[: max(1, min(3, len(fallback_candidates)))]

    candidates: list[SectionCandidate] = []
    for index, (title, start_index) in enumerate(title_positions):
        end_index = title_positions[index + 1][1] if index + 1 < len(title_positions) else len(normalized_text)
        section_text = normalized_text[start_index:end_index].strip()
        if not section_text:
            continue
        candidates.append(
            SectionCandidate(
                section_title=title,
                start_index=start_index,
                end_index=end_index,
                text=section_text,
                confidence=0.85,
                inferred=True,
            )
        )

    if not candidates:
        filtered_fallback = [
            item for item in fallback_candidates if item.section_title.strip().lower() not in ignored_titles
        ]
        if filtered_fallback:
            return filtered_fallback[: max(1, min(3, len(filtered_fallback)))]
        return fallback_candidates[: max(1, min(3, len(fallback_candidates)))]

    return candidates[: max(1, min(5, len(candidates)))]


def _build_fake_responses(
    *,
    source_pdf_path: Path,
    pdf_parse_output: PDFParseOutput,
    section_candidates: list[SectionCandidate],
    sections_for_analysis: list[SectionCandidate],
    references_for_summary: list[str],
    repair_on_audit: bool,
) -> list[dict[str, Any]]:
    section_index_payload = []
    for idx, item in enumerate(section_candidates, start=1):
        section_index_payload.append(
            {
                "section_id": f"s{idx}",
                "section_title": item.section_title,
                "section_level": 1,
                "page_start": 1,
                "page_end": 1,
                "order": idx,
                "is_inferred_boundary": item.inferred,
                "text_path": f"analysis/sections/section_{idx:02d}.txt",
            }
        )

    base_responses: list[dict[str, Any]] = [
        {
            "job_id": "job-safety-001",
            "source": {"source_type": "local_pdf", "source_value": str(source_pdf_path)},
            "presentation_style": "journal_club",
            "target_audience": "research_specialists",
            "language": "en",
            "output_formats": ["reveal", "pptx"],
            "target_duration_minutes": 20,
            "target_slide_count": 12,
            "automation_mode": "checkpointed",
            "approval_checkpoints_enabled": True,
            "checkpoints": ["parse_summary", "presentation_plan"],
            "reference_mode": "retrieve_all_light_summarize",
            "visual_policy": "balanced",
            "equation_policy": "avoid_unless_essential",
            "citation_style": "APA",
            "speaker_notes_style": "brief_talking_points",
            "user_notes": [],
            "defaults_applied": [],
            "warnings": [],
            "validation_errors": [],
        },
        {
            "source_status": {
                "acquired": True,
                "source_type": "local_pdf",
                "source_value": str(source_pdf_path),
                "stored_pdf_path": str(source_pdf_path),
                "notes": pdf_parse_output.warnings,
            },
            "metadata": {
                "title": source_pdf_path.stem,
                "authors": ["Unknown"],
                "venue_or_source": "local_pdf",
                "year": "unknown",
                "abstract": "",
                "keywords": [],
                "metadata_confidence": "low",
                "inferred_fields": ["title", "authors", "year"],
            },
            "section_index": section_index_payload,
            "full_text_path": "analysis/full_text.txt",
            "bibliography": {
                "detected": any(item.section_title.lower() == "references" for item in section_candidates),
                "references_count": len(references_for_summary),
                "references_raw_path": "references/references_raw.txt",
                "extraction_confidence": "low",
            },
            "parse_quality": {
                "ocr_used": False,
                "missing_pages": [],
                "garbled_regions": [],
                "suspected_parsing_issues": [],
                "warnings": pdf_parse_output.warnings,
                "overall_confidence": "medium" if pdf_parse_output.combined_text.strip() else "low",
            },
        },
    ]

    parsed_titles_for_mock = [
        str(item.get("section_title", "")).strip()
        for item in section_index_payload
        if isinstance(item, dict)
    ]
    predicted_sections_for_analysis = _select_sections_for_analysis(
        full_text=pdf_parse_output.combined_text,
        parsed_section_titles=parsed_titles_for_mock,
        fallback_candidates=sections_for_analysis,
    )

    for section_candidate in predicted_sections_for_analysis:
        base_responses.append(
            {
                "section_id": section_candidate.section_title.lower().replace(" ", "_")[:24] or "section",
                "section_title": section_candidate.section_title,
                "section_role": ["framing_background"],
                "summary": section_candidate.text[:240] or "Section summary unavailable.",
                "key_claims": [{"claim": "Presentation-relevant content exists.", "support_level_within_section": "weak", "notes": "Mocked A2 output."}],
                "important_details": [],
                "concepts_needing_explanation": [],
                "evidence_or_arguments": [],
                "limitations_or_cautions": [],
                "candidate_visualizable_ideas": [],
                "presentation_relevance": {
                    "importance_for_final_deck": "medium",
                    "why_it_matters": "From parsed section candidates.",
                    "likely_slide_use": ["supporting_context"],
                },
                "uncertainty_flags": ["Generated from mocked A2 response."],
                "confidence": "low",
            }
        )

    base_responses.append(
        {
            "artifacts": [],
            "summary": {
                "artifact_count": 0,
                "high_value_artifact_ids": [],
                "high_risk_artifact_ids": [],
                "equation_artifact_ids": [],
                "warnings": ["Artifact extraction remains mocked in V1."],
            },
        }
    )

    reference_entries = []
    for idx, text in enumerate(references_for_summary, start=1):
        reference_entries.append(
            {
                "reference_id": f"R{idx:03d}",
                "original_reference_text": text,
                "parsed_reference": {
                    "title": f"Reference {idx}",
                    "authors": ["Unknown"],
                    "venue_or_source": "unknown",
                    "year": "unknown",
                    "arxiv_id": "",
                    "doi": "",
                },
                "parsing_confidence": "low",
                "retrieval_status": "not_found",
                "matched_record": {
                    "title": "",
                    "authors": [],
                    "year": "",
                    "source": "other",
                    "url": "",
                    "pdf_path": "",
                    "reference_folder_path": "",
                },
                "match_confidence": "low",
                "alternative_candidates": [],
                "failure_reason": "Retrieval stubbed in V1",
                "notes": [],
            }
        )

    base_responses.append(
        {
            "reference_index": reference_entries,
            "retrieval_summary": {
                "total_references": len(reference_entries),
                "retrieved_count": 0,
                "ambiguous_count": 0,
                "not_found_count": len(reference_entries),
                "warnings": ["Reference retrieval is best-effort in V1."],
            },
        }
    )

    for idx in range(len(reference_entries)):
        base_responses.append(
            {
                "reference_id": f"R{idx + 1:03d}",
                "reference_title": f"Reference {idx + 1}",
                "summary": {
                    "main_topic": "Unknown",
                    "main_contribution": "Not retrieved in V1",
                    "brief_summary": "Summary unavailable because retrieval is stubbed.",
                },
                "relation_to_source_paper": {
                    "relation_type": ["background_context"],
                    "description": "Likely background context.",
                    "importance_for_source_presentation": "low",
                },
                "useful_points_for_main_presentation": [],
                "possible_useful_artifacts": [],
                "mention_recommendation": {
                    "should_mention_in_final_deck": False,
                    "recommended_scope": "none",
                    "rationale": "No reliable retrieval in V1.",
                },
                "warnings": ["Summary generated from limited metadata only."],
                "confidence": "low",
            }
        )

    base_responses.extend(
        [
            {
                "deck_metadata": {
                    "title": source_pdf_path.stem,
                    "subtitle": "Auto-generated plan",
                    "language": "en",
                    "presentation_style": "journal_club",
                    "target_audience": "research_specialists",
                    "target_duration_minutes": 20,
                    "target_slide_count": 12,
                },
                "narrative_arc": {
                    "overall_story": "Problem, method, results, and takeaways.",
                    "audience_adaptation_notes": ["Keep detail concise."],
                    "language_adaptation_notes": [],
                },
                "slides": [
                    {
                        "slide_number": 1,
                        "slide_role": "title",
                        "title": source_pdf_path.stem,
                        "objective": "Introduce the paper context.",
                        "key_points": ["Topic overview", "Why this matters"],
                        "must_avoid": ["Unsupported claims"],
                        "visuals": [
                            {
                                "visual_type": "text_only",
                                "asset_id": "none",
                                "source_origin": "none",
                                "usage_mode": "none",
                                "placement_hint": "center_focus",
                                "why_this_visual": "Simple first slide.",
                            }
                        ],
                        "source_support": [{"support_type": "source_section", "support_id": "s1", "support_note": "Opening section"}],
                        "citations": [{"short_citation": source_pdf_path.stem, "source_kind": "source_paper"}],
                        "speaker_note_hooks": ["Open with motivation."],
                        "confidence_notes": ["Plan built from mocked A6 output in V1."],
                        "layout_hint": "title with two bullets",
                    }
                ],
                "global_warnings": ["Planning model output is mocked in V1 workflow."],
                "plan_confidence": "low",
            },
            {
                "deck_language": "en",
                "notes_style": "brief_talking_points",
                "slide_notes": [
                    {
                        "slide_number": 1,
                        "slide_title": source_pdf_path.stem,
                        "talking_points": ["Introduce context", "Explain relevance", "Avoid overclaiming"],
                        "timing_hint_seconds": 60,
                        "caution_notes": [],
                    }
                ],
                "global_notes_warnings": [],
            },
            {
                "generated_visuals": [
                    {
                        "visual_id": "GV01",
                        "slide_number": 1,
                        "slide_title": source_pdf_path.stem,
                        "visual_purpose": "Simple conceptual context visual",
                        "visual_kind": "concept_map",
                        "status": "recommended",
                        "conceptual_basis": {
                            "grounded_in_source_sections": ["s1"],
                            "grounded_in_source_artifacts": [],
                            "grounded_in_reference_ids": [],
                        },
                        "provenance_label": "conceptual",
                        "must_preserve_if_adapted": [],
                        "visual_spec": {
                            "composition": "Title node with two supporting nodes",
                            "main_elements": ["Problem", "Method"],
                            "labels_or_text": ["Context", "Approach"],
                            "style_notes": ["Clean lines", "Minimal labels"],
                            "language": "en",
                        },
                        "safety_notes": ["Do not present as empirical evidence"],
                        "image_generation_prompt": "Concept map with problem and approach nodes",
                    }
                ],
                "global_visual_warnings": ["Visual specs only; no image provider configured."],
            },
            {
                "render_status": "success",
                "output": {
                    "reveal_root_path": "presentation/reveal",
                    "entry_html_path": "presentation/reveal/index.html",
                    "assets_directory": "presentation/reveal/assets",
                    "theme_name": "minimal-v1",
                },
                "slide_render_results": [
                    {
                        "slide_number": 1,
                        "title": source_pdf_path.stem,
                        "status": "rendered_with_warning",
                        "assets_used": [],
                        "citations_rendered": [source_pdf_path.stem],
                        "notes_attached": True,
                        "warnings": ["Visual placeholder used"],
                    }
                ],
                "global_warnings": ["LLM render planning mocked in V1."],
                "deviations": [],
            },
            {
                "build_status": "success",
                "output": {
                    "pptx_path": "presentation/pptx/deck.pptx",
                    "template_used": "default",
                    "notes_insertion_supported": True,
                },
                "slide_build_results": [
                    {
                        "slide_number": 1,
                        "title": source_pdf_path.stem,
                        "status": "built_with_warning",
                        "assets_used": [],
                        "notes_inserted": True,
                        "citations_inserted": True,
                        "warnings": ["Visual placeholders only"],
                    }
                ],
                "global_warnings": ["LLM build planning mocked in V1."],
                "deviations": [],
            },
            {
                "audit_status": "completed_with_warnings",
                "deck_risk_level": "high",
                "slide_audits": [
                    {
                        "slide_number": 1,
                        "slide_title": source_pdf_path.stem,
                        "overall_support": "weakly_supported",
                        "findings": [
                            {
                                "severity": "high",
                                "category": "unsupported_claim",
                                "description": "One bullet appears weakly grounded.",
                                "evidence_basis": [{"source_type": "presentation_plan", "source_id": "s1", "note": "Needs stricter wording"}],
                                "recommended_fix": "Simplify claim and add caveat",
                            },
                            {
                                "severity": "high",
                                "category": "generated_visual_overreach",
                                "description": "Visual may look evidentiary.",
                                "evidence_basis": [{"source_type": "render_output", "source_id": "GV01", "note": "Placeholder styling unclear"}],
                                "recommended_fix": "Mark conceptual provenance clearly",
                            },
                            {
                                "severity": "medium",
                                "category": "citation_issue",
                                "description": "Citation could be more explicit.",
                                "evidence_basis": [{"source_type": "presentation_plan", "source_id": "slide1", "note": "Single citation too generic"}],
                                "recommended_fix": "Tighten citation text",
                            },
                            {
                                "severity": "medium",
                                "category": "notes_issue",
                                "description": "Notes include broad phrasing.",
                                "evidence_basis": [{"source_type": "speaker_notes", "source_id": "slide1", "note": "Could overstate"}],
                                "recommended_fix": "Trim to conservative wording",
                            },
                            {
                                "severity": "low",
                                "category": "translation_drift",
                                "description": "Potential tone drift risk if translated.",
                                "evidence_basis": [{"source_type": "speaker_notes", "source_id": "slide1", "note": "Future multilingual risk"}],
                                "recommended_fix": "Keep terminology stable",
                            },
                        ],
                        "required_action": "revise_slide",
                    }
                ],
                "deck_level_findings": [],
                "repair_priority": [
                    {"priority_order": 1, "slide_number": 1, "reason": "Fix unsupported claims first"},
                    {"priority_order": 2, "slide_number": 1, "reason": "Constrain visual overreach"},
                ],
                "global_warnings": ["First safety pass found high-severity items."],
            },
        ]
    )

    if repair_on_audit:
        base_responses.extend(
            [
                {
                    "repair_status": "applied",
                    "target_ids": ["slide_1"],
                    "changes_made": ["Simplified risky claims"],
                    "unresolved_risks": [],
                    "repair_confidence": "medium",
                    "warnings": [],
                },
                {
                    "repair_status": "applied",
                    "target_ids": ["slide_1"],
                    "changes_made": ["Tightened citation mapping"],
                    "unresolved_risks": [],
                    "repair_confidence": "medium",
                    "warnings": [],
                },
                {
                    "repair_status": "applied",
                    "target_ids": ["GV01"],
                    "changes_made": ["Marked visual as conceptual"],
                    "unresolved_risks": [],
                    "repair_confidence": "medium",
                    "warnings": [],
                },
                {
                    "repair_status": "applied",
                    "target_ids": ["slide_note_1"],
                    "changes_made": ["Trimmed over-broad notes"],
                    "unresolved_risks": [],
                    "repair_confidence": "medium",
                    "warnings": [],
                },
                {
                    "repair_status": "applied",
                    "target_ids": ["deck"],
                    "changes_made": ["Added translation-fidelity caution"],
                    "unresolved_risks": [],
                    "repair_confidence": "low",
                    "warnings": [],
                },
                {
                    "audit_status": "completed_with_warnings",
                    "deck_risk_level": "medium",
                    "slide_audits": [
                        {
                            "slide_number": 1,
                            "slide_title": source_pdf_path.stem,
                            "overall_support": "supported",
                            "findings": [
                                {
                                    "severity": "medium",
                                    "category": "citation_issue",
                                    "description": "Citation text could still be improved.",
                                    "evidence_basis": [
                                        {
                                            "source_type": "presentation_plan",
                                            "source_id": "slide1",
                                            "note": "Generic citation remains",
                                        }
                                    ],
                                    "recommended_fix": "Manual review if needed",
                                }
                            ],
                            "required_action": "add_citation",
                        }
                    ],
                    "deck_level_findings": [],
                    "repair_priority": [{"priority_order": 1, "slide_number": 1, "reason": "Optional citation tightening"}],
                    "global_warnings": ["Second audit shows lower risk after one repair cycle."],
                },
            ]
        )

    return base_responses


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError("Expected true|false")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sequential A0->A11 workflow on a local PDF")
    parser.add_argument("--pdf", required=True, help="Path to a local PDF file")
    parser.add_argument("--repair-on-audit", default="true", help="Whether to run one repair cycle: true|false")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_workflow(Path(args.pdf), repair_on_audit=_parse_bool(args.repair_on_audit))
