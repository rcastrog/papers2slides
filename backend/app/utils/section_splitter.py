"""Best-effort academic section splitting utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SECTION_PATTERN = re.compile(
    r"(?im)^\s*(?:\d+(?:\.\d+)*)?\s*(abstract|introduction|related work|background|method|methods|experiments?|results?|discussion|conclusion|references)\s*$"
)


@dataclass(slots=True)
class SectionCandidate:
    """A lightweight section candidate derived from raw extracted text."""

    section_title: str
    start_index: int
    end_index: int
    text: str
    confidence: float
    inferred: bool


def split_into_sections(text: str) -> list[SectionCandidate]:
    """Split extracted paper text into ordered section candidates."""
    normalized_text = text or ""
    if not normalized_text.strip():
        return []

    matches = list(_SECTION_PATTERN.finditer(normalized_text))
    if not matches:
        return [
            SectionCandidate(
                section_title="Full Text",
                start_index=0,
                end_index=len(normalized_text),
                text=normalized_text.strip(),
                confidence=0.2,
                inferred=True,
            )
        ]

    candidates: list[SectionCandidate] = []
    for index, match in enumerate(matches):
        section_start = match.start()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_text)

        raw_title = match.group(1)
        title = _normalize_title(raw_title)
        section_text = normalized_text[section_start:section_end].strip()
        if not section_text:
            continue

        candidates.append(
            SectionCandidate(
                section_title=title,
                start_index=section_start,
                end_index=section_end,
                text=section_text,
                confidence=0.9,
                inferred=False,
            )
        )

    if not candidates:
        return [
            SectionCandidate(
                section_title="Full Text",
                start_index=0,
                end_index=len(normalized_text),
                text=normalized_text.strip(),
                confidence=0.2,
                inferred=True,
            )
        ]
    return candidates


def _normalize_title(value: str) -> str:
    return " ".join(token.capitalize() for token in value.strip().split())
