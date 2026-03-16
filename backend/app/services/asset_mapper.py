"""Conservative V1 mapping from artifact manifest entries to extracted files."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from app.models.artifact_manifest import ArtifactManifest
from app.services.pdf_artifact_extractor import ExtractedArtifactBundle


@dataclass(slots=True)
class AssetMapEntry:
    """One mapping decision for a manifest artifact."""

    artifact_id: str
    page_numbers: list[int]
    candidate_asset_ids: list[str]
    selected_asset_id: str | None
    resolved_path: str | None
    status: str
    confidence: str
    decision_reason: str
    warnings: list[str]
    matching_signals: dict[str, Any]


@dataclass(slots=True)
class AssetMap:
    """Resolver output consumed by renderers and workflow diagnostics."""

    map: dict[str, str]
    entries: list[AssetMapEntry]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "map": dict(self.map),
            "entries": [asdict(entry) for entry in self.entries],
            "warnings": list(self.warnings),
        }


class AssetMapper:
    """Build a conservative artifact_id -> file_path map."""

    def build_asset_map(self, artifact_manifest: ArtifactManifest, extracted_assets: ExtractedArtifactBundle) -> AssetMap:
        """Map each manifest artifact_id to a single extracted asset path when confidence is acceptable."""
        by_page: dict[int, list[dict[str, Any]]] = {}
        for extracted in extracted_assets.extracted_assets:
            candidate = Path(extracted.file_path)
            if candidate.is_file():
                by_page.setdefault(extracted.page_number, []).append(
                    {
                        "asset_id": extracted.asset_id,
                        "path": candidate.resolve(),
                        "page_number": extracted.page_number,
                        "image_index": self._extract_image_index(extracted.asset_id),
                        "notes": list(extracted.notes),
                    }
                )

        resolved_map: dict[str, str] = {}
        entries: list[AssetMapEntry] = []
        warnings: list[str] = list(extracted_assets.warnings)

        artifacts_by_page: dict[int, list[Any]] = {}
        for artifact in artifact_manifest.artifacts:
            for page_number in artifact.page_numbers:
                artifacts_by_page.setdefault(page_number, []).append(artifact)

        for artifact in artifact_manifest.artifacts:
            page_candidates: list[dict[str, Any]] = []
            candidate_warnings: list[str] = []
            matching_signals: dict[str, Any] = {
                "page_numbers": list(artifact.page_numbers),
            }

            for page_number in artifact.page_numbers:
                page_candidates.extend(by_page.get(page_number, []))

            unique_candidates: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for candidate in page_candidates:
                asset_id = str(candidate.get("asset_id", "")).strip()
                if not asset_id or asset_id in seen_ids:
                    continue
                seen_ids.add(asset_id)
                unique_candidates.append(candidate)

            candidate_asset_ids = sorted(str(item["asset_id"]) for item in unique_candidates)
            matching_signals["candidate_count"] = len(candidate_asset_ids)

            selected = self._select_candidate(
                artifact=artifact,
                candidates=unique_candidates,
                artifacts_by_page=artifacts_by_page,
                matching_signals=matching_signals,
                candidate_warnings=candidate_warnings,
            )

            if selected is None:
                status = "unresolved"
                confidence = "unresolved"
                decision_reason = "no_confident_candidate"
                if len(unique_candidates) > 1:
                    status = "ambiguous"
                    confidence = "ambiguous"
                    decision_reason = "multiple_candidates_without_strong_signal"
                elif len(unique_candidates) == 0:
                    decision_reason = "no_candidates_on_artifact_pages"

                entry_warnings = list(candidate_warnings)
                if status in {"unresolved", "ambiguous"}:
                    entry_warnings.append(decision_reason)
                    warnings.append(
                        f"AssetMapper {status} {artifact.artifact_id}: {decision_reason} (pages={artifact.page_numbers})"
                    )

                entries.append(
                    AssetMapEntry(
                        artifact_id=artifact.artifact_id,
                        page_numbers=list(artifact.page_numbers),
                        candidate_asset_ids=candidate_asset_ids,
                        selected_asset_id=None,
                        resolved_path=None,
                        status=status,
                        confidence=confidence,
                        decision_reason=decision_reason,
                        warnings=entry_warnings,
                        matching_signals=matching_signals,
                    )
                )
                continue

            resolved_path = str(selected["path"])
            resolved_map[artifact.artifact_id] = resolved_path
            entries.append(
                AssetMapEntry(
                    artifact_id=artifact.artifact_id,
                    page_numbers=list(artifact.page_numbers),
                    candidate_asset_ids=candidate_asset_ids,
                    selected_asset_id=str(selected["asset_id"]),
                    resolved_path=resolved_path,
                    status="resolved",
                    confidence=str(matching_signals.get("resolved_confidence", "page_exact")),
                    decision_reason=str(matching_signals.get("resolved_reason", "resolved")),
                    warnings=list(candidate_warnings),
                    matching_signals=matching_signals,
                )
            )

        return AssetMap(map=resolved_map, entries=entries, warnings=warnings)

    def _select_candidate(
        self,
        *,
        artifact: Any,
        candidates: list[dict[str, Any]],
        artifacts_by_page: dict[int, list[Any]],
        matching_signals: dict[str, Any],
        candidate_warnings: list[str],
    ) -> dict[str, Any] | None:
        if len(candidates) == 0:
            return None
        if len(candidates) == 1:
            matching_signals["resolved_reason"] = "unique_candidate_on_pages"
            matching_signals["resolved_confidence"] = "high"
            return candidates[0]

        figure_hint = self._extract_figure_hint_number(f"{artifact.artifact_label} {artifact.caption}")
        matching_signals["figure_hint_number"] = figure_hint
        if figure_hint is not None:
            hinted = [candidate for candidate in candidates if candidate.get("image_index") == figure_hint]
            if len(hinted) == 1 and len(candidates) <= 4:
                matching_signals["resolved_reason"] = "figure_hint_unique_match"
                matching_signals["resolved_confidence"] = "medium"
                return hinted[0]
            if len(hinted) > 1:
                candidate_warnings.append("figure_hint_matches_multiple_candidates")

        overlap_scores: dict[str, int] = {}
        caption_tokens = self._tokenize(f"{artifact.artifact_label} {artifact.caption}")
        matching_signals["caption_token_count"] = len(caption_tokens)
        if caption_tokens:
            for candidate in candidates:
                notes_tokens = self._tokenize(" ".join(str(note) for note in candidate.get("notes", [])))
                score = len(caption_tokens.intersection(notes_tokens))
                overlap_scores[str(candidate["asset_id"])] = score

            matching_signals["caption_overlap_scores"] = overlap_scores
            best_score = max(overlap_scores.values()) if overlap_scores else 0
            best_candidates = [candidate for candidate in candidates if overlap_scores.get(str(candidate["asset_id"]), 0) == best_score]
            if best_score >= 2 and len(best_candidates) == 1 and len(candidates) <= 4:
                matching_signals["resolved_reason"] = "caption_overlap_unique_match"
                matching_signals["resolved_confidence"] = "medium"
                return best_candidates[0]

        if len(artifact.page_numbers) == 1 and len(candidates) <= 4:
            page_number = artifact.page_numbers[0]
            page_artifacts = artifacts_by_page.get(page_number, [])
            if len(page_artifacts) > 1:
                try:
                    artifact_rank = page_artifacts.index(artifact) + 1
                except ValueError:
                    artifact_rank = None
                matching_signals["artifact_rank_on_page"] = artifact_rank
                if artifact_rank is not None:
                    rank_matches = [candidate for candidate in candidates if candidate.get("image_index") == artifact_rank]
                    if len(rank_matches) == 1:
                        matching_signals["resolved_reason"] = "page_order_rank_match"
                        matching_signals["resolved_confidence"] = "low"
                        return rank_matches[0]

        return None

    @staticmethod
    def _extract_image_index(asset_id: str) -> int | None:
        match = re.search(r"IMG(\d+)$", str(asset_id).strip(), flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _extract_figure_hint_number(text: str) -> int | None:
        match = re.search(r"(?:fig(?:ure)?|table|chart|diagram|eq(?:uation)?)\s*(\d+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if len(token) >= 4 and not token.isdigit()
        }
