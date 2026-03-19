"""Helpers to classify repeated and near-repeated slide bullets."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

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


@dataclass(frozen=True)
class BulletHighlightConfig:
    near_threshold: float = 0.74
    min_chars_for_similarity: int = 28


def normalize_bullet_key(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    normalized = re.sub(r"[\s\.,;:!\?]+$", "", normalized)
    return normalized


def build_presentation_bullet_highlight_labels(
    *,
    slides: list[dict[str, object]],
    config: BulletHighlightConfig | None = None,
) -> dict[str, str]:
    """Return normalized bullet text to highlight label.

    Labels:
    - repeated: exact duplicates across slides
    - near_repeated: semantically near duplicates across slides
    """
    active = config or BulletHighlightConfig()

    bullets: list[tuple[str, str]] = []
    counts: dict[str, int] = {}

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        for point in slide.get("key_points", []) or []:
            text = re.sub(r"\s+", " ", str(point or "").strip())
            key = normalize_bullet_key(text)
            if not key:
                continue
            bullets.append((text, key))
            counts[key] = counts.get(key, 0) + 1

    labels: dict[str, str] = {}

    for key, count in counts.items():
        if count > 1:
            labels[key] = "repeated"

    candidate_indexes = [
        index
        for index, (text, key) in enumerate(bullets)
        if len(text) >= active.min_chars_for_similarity and labels.get(key) != "repeated"
    ]

    for left_pos, left_index in enumerate(candidate_indexes):
        left_text, left_key = bullets[left_index]
        for right_index in candidate_indexes[left_pos + 1 :]:
            right_text, right_key = bullets[right_index]
            if left_key == right_key:
                continue
            if labels.get(left_key) == "repeated" or labels.get(right_key) == "repeated":
                continue
            score = semantic_similarity_score(left_text, right_text)
            if score >= active.near_threshold:
                labels.setdefault(left_key, "near_repeated")
                labels.setdefault(right_key, "near_repeated")

    return labels


def semantic_similarity_score(left: str, right: str) -> float:
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
    return re.sub(r"\s+", " ", text).strip()


def _tokenize_similarity(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in value.split():
        if token in _SEMANTIC_STOPWORDS:
            continue
        if len(token) <= 2:
            continue

        normalized = token
        if normalized.endswith("ing") and len(normalized) > 5:
            normalized = normalized[:-3]
        elif normalized.endswith("ed") and len(normalized) > 4:
            normalized = normalized[:-2]
        elif normalized.endswith("es") and len(normalized) > 4:
            normalized = normalized[:-2]
        elif normalized.endswith("s") and len(normalized) > 3:
            normalized = normalized[:-1]

        tokens.add(normalized)
    return tokens
