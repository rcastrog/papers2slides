"""Best-effort bibliography extraction from parsed paper text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ReferenceParseOutput:
    """Deterministic reference extraction result."""

    references_raw: list[str]
    count: int
    warnings: list[str]


class ReferenceParser:
    """Extract references from text using lightweight heuristics."""

    _REFERENCES_HEADER_PATTERN = re.compile(r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*references\s*$")
    _SPLIT_PATTERN = re.compile(r"(?m)^\s*(?:\[\d+\]|\d+\.|\d+\))\s+")
    _TAIL_MARKERS = [
        re.compile(r"(?im)^\s*attention\s+visualizations\s*$"),
        re.compile(r"(?im)^\s*appendix\b"),
        re.compile(r"(?im)^\s*input-input\s+layer\d+\s*$"),
    ]
    _REFERENCE_START_PATTERN = re.compile(
        r"^\s*(?:\[\d+\]|\d+\.|\d+\))?\s*(?:[A-Z][A-Za-z'`-]{1,30},\s|[A-Z][A-Za-z'`-]{1,30}\s+[A-Z][A-Za-z'`-]{1,30},\s)"
    )

    def extract_references(self, text: str) -> ReferenceParseOutput:
        """Extract raw bibliography entries from full text or references-only text."""
        warnings: list[str] = []
        normalized_text = (text or "").strip()
        if not normalized_text:
            return ReferenceParseOutput(references_raw=[], count=0, warnings=["Input text is empty"])

        references_text = normalized_text
        header_match = self._REFERENCES_HEADER_PATTERN.search(normalized_text)
        if header_match is not None:
            references_text = normalized_text[header_match.end() :].strip()
        else:
            warnings.append("Could not locate a dedicated References header; parsing whole text")

        if not references_text:
            return ReferenceParseOutput(references_raw=[], count=0, warnings=warnings + ["References text is empty"])

        references_text, truncated_tail = self._truncate_non_reference_tail(references_text)
        if truncated_tail:
            warnings.append("Trimmed non-reference appendix/visualization text after bibliography section")

        split_positions = [match.start() for match in self._SPLIT_PATTERN.finditer(references_text)]
        references_raw: list[str]
        if split_positions:
            references_raw = self._split_by_positions(references_text, split_positions)
        else:
            references_raw = self._split_unordered_bibliography(references_text)
            if len(references_raw) <= 1:
                references_raw = self._split_by_blank_lines(references_text)
                warnings.append("Could not detect numbered references; used paragraph splitting")
            else:
                warnings.append("Could not detect numbered references; used line-based bibliography heuristics")

        cleaned_references = [self._normalize_reference_chunk(entry) for entry in references_raw if entry and entry.strip()]
        cleaned_references = [entry for entry in cleaned_references if entry]
        if not cleaned_references:
            warnings.append("No reference entries were extracted")

        return ReferenceParseOutput(
            references_raw=cleaned_references,
            count=len(cleaned_references),
            warnings=warnings,
        )

    @staticmethod
    def _split_by_positions(text: str, positions: list[int]) -> list[str]:
        chunks: list[str] = []
        for index, start in enumerate(positions):
            end = positions[index + 1] if index + 1 < len(positions) else len(text)
            chunk = text[start:end].strip()
            if not chunk:
                continue
            chunks.append(chunk)
        return chunks

    @staticmethod
    def _split_by_blank_lines(text: str) -> list[str]:
        return [chunk for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]

    @classmethod
    def _split_unordered_bibliography(cls, text: str) -> list[str]:
        """Best-effort split for unnumbered bibliography sections.

        This handles wrapped citation lines where a single reference spans multiple
        lines and a new reference often begins with a surname-like token.
        """
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return []

        entries: list[str] = []
        current_parts: list[str] = []

        for line in lines:
            is_new_reference = bool(cls._REFERENCE_START_PATTERN.match(line))
            if is_new_reference and current_parts:
                entries.append(" ".join(current_parts).strip())
                current_parts = [line]
            else:
                current_parts.append(line)

        if current_parts:
            entries.append(" ".join(current_parts).strip())

        return [item for item in entries if item]

    @classmethod
    def _truncate_non_reference_tail(cls, text: str) -> tuple[str, bool]:
        cutoff = None
        for pattern in cls._TAIL_MARKERS:
            match = pattern.search(text)
            if match is None:
                continue
            cutoff = match.start() if cutoff is None else min(cutoff, match.start())

        if cutoff is None:
            return text, False
        return text[:cutoff].strip(), True

    @staticmethod
    def _normalize_reference_chunk(text: str) -> str:
        chunk = str(text or "").strip()
        if not chunk:
            return ""

        # Repair line-wrap hyphenation from PDF extraction.
        chunk = re.sub(r"([A-Za-z])-(?:\s*\n\s*)([a-z])", r"\1\2", chunk)
        chunk = re.sub(r"\s*\n\s*", " ", chunk)
        chunk = re.sub(r"\s+", " ", chunk)
        return chunk.strip()
