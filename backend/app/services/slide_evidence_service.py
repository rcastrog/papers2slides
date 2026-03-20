"""Read-model service for slide evidence inspection payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.api.schemas import ClaimEvidence, SlideEvidence, SlideEvidenceResponse
from app.storage.run_manager import RunManager


class SlideEvidenceService:
    """Map run artifacts into deterministic slide evidence DTOs."""

    def __init__(self, run_path: Path) -> None:
        self._run_path = run_path.resolve()
        self._run_manager = RunManager(self._run_path.parent)
        self._run_manager.set_run_path(self._run_path)

    def build_evidence(self) -> SlideEvidenceResponse:
        """Build run-level slide evidence payload from persisted artifacts."""
        run_manifest = self._run_manager.read_json("logs/run_manifest.json") or {}
        plan_payload = self._run_manager.read_first_json(
            [
                "presentation/presentation_plan_repaired.json",
                "presentation/presentation_plan.json",
            ]
        ) or {}
        audit_payload = self._run_manager.read_first_json(
            [
                "audit/audit_report_final.json",
                "audit/audit_report_initial.json",
            ]
        ) or {}
        reference_payload = self._run_manager.read_json("references/reference_index.json") or {}

        slide_quality_flags = self._build_slide_quality_flags(audit_payload)
        citation_link_index = self._build_citation_link_index(reference_payload)

        warnings: list[str] = []
        slides_raw = plan_payload.get("slides", [])
        if not isinstance(slides_raw, list):
            slides_raw = []
        if not slides_raw:
            warnings.append("Slide evidence unavailable: presentation plan has no slides.")

        slides: list[SlideEvidence] = []
        for slide_idx, slide in enumerate(slides_raw, start=1):
            if not isinstance(slide, dict):
                continue

            slide_number = int(slide.get("slide_number", 0) or 0) or slide_idx
            slide_id = f"slide-{slide_number}"
            slide_title = str(slide.get("title", "")).strip() or f"Slide {slide_number}"

            key_points_raw = slide.get("key_points", [])
            key_points = [str(item).strip() for item in key_points_raw if str(item).strip()] if isinstance(key_points_raw, list) else []

            confidence_notes_raw = slide.get("confidence_notes", [])
            confidence_flags = [str(item).strip() for item in confidence_notes_raw if str(item).strip()] if isinstance(confidence_notes_raw, list) else []

            citations_raw = slide.get("citations", [])
            citation_labels: list[str] = []
            if isinstance(citations_raw, list):
                for citation in citations_raw:
                    if not isinstance(citation, dict):
                        continue
                    label = str(citation.get("short_citation", "")).strip()
                    if label:
                        citation_labels.append(label)

            citation_links = self._resolve_citation_links(citation_labels, citation_link_index)

            source_support_raw = slide.get("source_support", [])
            support_ids: list[str] = []
            source_snippets: list[str] = []
            if isinstance(source_support_raw, list):
                for support in source_support_raw:
                    if not isinstance(support, dict):
                        continue
                    support_id = str(support.get("support_id", "")).strip()
                    support_note = str(support.get("support_note", "")).strip()
                    if support_id:
                        support_ids.append(support_id)
                    if support_note:
                        source_snippets.append(support_note)

            per_slide_quality = list(slide_quality_flags.get(slide_number, []))
            claims: list[ClaimEvidence] = []
            no_evidence_claim_count = 0

            for claim_idx, claim_text in enumerate(key_points, start=1):
                no_evidence = not citation_labels and not source_snippets
                if no_evidence:
                    no_evidence_claim_count += 1

                claim_quality = list(per_slide_quality)
                if no_evidence:
                    claim_quality.append("no_evidence")

                claim_confidence = self._derive_claim_confidence(
                    confidence_flags=confidence_flags,
                    quality_flags=claim_quality,
                    no_evidence=no_evidence,
                )

                claims.append(
                    ClaimEvidence(
                        claim_id=f"{slide_id}-claim-{claim_idx}",
                        claim_text=claim_text,
                        confidence_flag=claim_confidence,
                        quality_flags=claim_quality,
                        citation_labels=citation_labels,
                        citation_links=citation_links,
                        source_snippets=source_snippets,
                        support_ids=support_ids,
                        no_evidence=no_evidence,
                    )
                )

            if no_evidence_claim_count > 0 and "no_evidence" not in per_slide_quality:
                per_slide_quality.append("no_evidence")

            slides.append(
                SlideEvidence(
                    slide_number=slide_number,
                    slide_id=slide_id,
                    slide_title=slide_title,
                    claim_count=len(claims),
                    no_evidence_claim_count=no_evidence_claim_count,
                    confidence_flags=confidence_flags,
                    quality_flags=per_slide_quality,
                    claims=claims,
                )
            )

        return SlideEvidenceResponse(
            run_id=str(run_manifest.get("run_id") or self._run_path.name),
            run_status=str(run_manifest.get("status", "")).strip() or None,
            slides=slides,
            warnings=warnings,
        )

    @staticmethod
    def _build_slide_quality_flags(audit_payload: dict[str, Any]) -> dict[int, list[str]]:
        slide_flags: dict[int, list[str]] = {}
        slide_audits = audit_payload.get("slide_audits", []) if isinstance(audit_payload, dict) else []
        if not isinstance(slide_audits, list):
            return slide_flags

        for item in slide_audits:
            if not isinstance(item, dict):
                continue
            slide_number = int(item.get("slide_number", 0) or 0)
            if slide_number <= 0:
                continue

            flags: list[str] = []
            overall_support = str(item.get("overall_support", "")).strip().lower()
            if overall_support:
                flags.append(f"overall_support:{overall_support}")

            findings = item.get("findings", [])
            if isinstance(findings, list):
                for finding in findings:
                    if not isinstance(finding, dict):
                        continue
                    severity = str(finding.get("severity", "")).strip().lower()
                    category = str(finding.get("category", "")).strip().lower()
                    if severity and category:
                        flags.append(f"{severity}:{category}")
                    elif category:
                        flags.append(category)

            slide_flags[slide_number] = sorted(set(flags))

        return slide_flags

    @staticmethod
    def _build_citation_link_index(reference_payload: dict[str, Any]) -> dict[str, str]:
        index: dict[str, str] = {}
        entries = reference_payload.get("reference_index", []) if isinstance(reference_payload, dict) else []
        if not isinstance(entries, list):
            return index

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            matched_record = entry.get("matched_record", {})
            if not isinstance(matched_record, dict):
                matched_record = {}
            link = str(matched_record.get("url", "")).strip()
            if not link:
                continue

            parsed_reference = entry.get("parsed_reference", {})
            if not isinstance(parsed_reference, dict):
                parsed_reference = {}

            year = str(parsed_reference.get("year", "")).strip()
            title = str(parsed_reference.get("title", "")).strip()
            authors = parsed_reference.get("authors", [])
            first_author = ""
            if isinstance(authors, list) and authors:
                first_author = str(authors[0]).strip().split(" ")[-1].lower()

            if title:
                index[title.strip().lower()] = link
            if year and first_author:
                index[f"{first_author}:{year}"] = link

        return index

    @staticmethod
    def _resolve_citation_links(citation_labels: list[str], citation_link_index: dict[str, str]) -> list[str]:
        links: list[str] = []
        for label in citation_labels:
            normalized = label.strip().lower()
            direct = citation_link_index.get(normalized)
            if direct:
                links.append(direct)
                continue

            parts = [part.strip() for part in label.split(",") if part.strip()]
            if len(parts) >= 2:
                surname = parts[0].split(" ")[-1].lower()
                year = parts[-1]
                candidate = citation_link_index.get(f"{surname}:{year}")
                if candidate:
                    links.append(candidate)

        return sorted(set(links))

    @staticmethod
    def _derive_claim_confidence(*, confidence_flags: list[str], quality_flags: list[str], no_evidence: bool) -> str:
        if no_evidence:
            return "low"

        lowered_flags = " ".join(item.lower() for item in confidence_flags)
        if "high" in lowered_flags:
            return "high"
        if "low" in lowered_flags:
            return "low"

        high_risk_markers = ["unsupported", "overclaim", "high:"]
        if any(marker in flag for flag in quality_flags for marker in high_risk_markers):
            return "low"

        return "medium"
