"""OpenAI-backed conceptual image generation for A8 outputs."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from app.models.generated_visuals import GeneratedVisualEntry


@dataclass(frozen=True)
class ImageGenerationSettings:
    enabled: bool = False
    model: str = "dall-e-3"
    size: str = "1792x1024"
    quality: str = "hd"
    max_images_per_run: int = 4
    max_retries_per_image: int = 2
    retry_delay_seconds: float = 1.0


class OpenAIConceptualImageGenerator:
    """Generate conceptual images with cost/safety controls and prompt caching."""

    def __init__(
        self,
        *,
        api_key: str,
        settings: ImageGenerationSettings,
        cache_dir: Path,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._settings = settings
        self._cache_dir = cache_dir

    def materialize(
        self,
        *,
        entries: list[GeneratedVisualEntry],
        run_assets_dir: Path,
    ) -> tuple[dict[str, str], list[str]]:
        """Generate images for conceptual entries and return visual_id->path map + warnings."""
        if not self._settings.enabled:
            return {}, ["OpenAI image generation disabled; using deterministic SVG fallback."]

        if not self._api_key:
            return {}, ["OPENAI_API_KEY missing; using deterministic SVG fallback."]

        candidates = [
            item
            for item in entries
            if item.provenance_label == "conceptual" and item.status != "not_needed"
        ]
        if not candidates:
            return {}, []

        selected = candidates[: max(0, self._settings.max_images_per_run)]
        skipped = len(candidates) - len(selected)
        warnings: list[str] = []
        if skipped > 0:
            warnings.append(
                f"Image generation capped at {self._settings.max_images_per_run} per run; skipped {skipped} conceptual visuals."
            )

        run_assets_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        client = self._build_openai_client(self._api_key)
        resolved: dict[str, str] = {}

        for entry in selected:
            prompt = _build_postprocessed_prompt(entry)
            cache_key = _cache_key(
                prompt=prompt,
                model=self._settings.model,
                size=self._settings.size,
                quality=self._settings.quality,
            )
            cache_file = self._cache_dir / f"{cache_key}.png"
            target_file = run_assets_dir / f"{entry.visual_id}.png"

            if cache_file.is_file():
                shutil.copy2(cache_file, target_file)
                resolved[entry.visual_id] = str(target_file.resolve())
                continue

            image_bytes: bytes | None = None
            last_error = ""
            for attempt in range(self._settings.max_retries_per_image + 1):
                try:
                    response = client.images.generate(
                        model=self._settings.model,
                        prompt=prompt,
                        size=self._settings.size,
                        quality=self._settings.quality,
                        n=1,
                        response_format="b64_json",
                    )
                    b64_data = response.data[0].b64_json if response and response.data else None
                    if not b64_data:
                        raise RuntimeError("OpenAI image response missing b64_json payload")
                    image_bytes = base64.b64decode(b64_data)
                    break
                except Exception as exc:  # pragma: no cover - exercised in integration, not unit
                    last_error = str(exc)
                    if attempt >= self._settings.max_retries_per_image:
                        break
                    time.sleep(self._settings.retry_delay_seconds)

            if image_bytes is None:
                warnings.append(f"Image generation failed for {entry.visual_id}: {last_error}")
                continue

            cache_file.write_bytes(image_bytes)
            target_file.write_bytes(image_bytes)
            resolved[entry.visual_id] = str(target_file.resolve())

        return resolved, warnings

    @staticmethod
    def _build_openai_client(api_key: str):
        try:
            openai_module = importlib.import_module("openai")
            openai_cls = getattr(openai_module, "OpenAI")
        except Exception as exc:  # pragma: no cover - import errors depend on runtime env
            raise RuntimeError("openai package is required for image generation. Install with 'pip install openai'.") from exc

        return openai_cls(api_key=api_key)


def _build_postprocessed_prompt(entry: GeneratedVisualEntry) -> str:
    """Compress noisy A8 prompt text into cleaner image-model instructions."""
    style_notes = ", ".join(entry.visual_spec.style_notes[:3]) if entry.visual_spec.style_notes else "clean modern presentation style"

    key_labels = [_extract_primary_clause(item) for item in entry.visual_spec.labels_or_text]
    key_labels = [item for item in key_labels if item][:5]
    labels_text = "; ".join(key_labels) if key_labels else "no labels"

    main_elements = [_extract_primary_clause(item) for item in entry.visual_spec.main_elements]
    main_elements = [item for item in main_elements if item][:4]
    elements_text = "; ".join(main_elements) if main_elements else "clear conceptual components"

    return (
        "Create a polished conceptual presentation visual. "
        f"Slide title: {entry.slide_title}. "
        f"Purpose: {entry.visual_purpose}. "
        f"Visual type: {entry.visual_kind.replace('_', ' ')}. "
        f"Composition guidance: {_truncate(entry.visual_spec.composition, 300)}. "
        f"Core elements: {elements_text}. "
        f"Concept anchors (for structure only, not rendered text): {labels_text}. "
        f"Style: {style_notes}. "
        "Use a clean professional 16:9 layout, high contrast, balanced spacing, and iconographic simplicity. "
        "Do not render words, letters, numbers, equations, or legends inside the image. "
        "Convey meaning using shapes, arrows, grouping, and icons only. "
        "Avoid gibberish text artifacts and decorative pseudo-typography. "
        "Do not include empirical numbers or claims not present in the prompt. "
        "No logos, no watermarks, no brand names."
    )


def _cache_key(*, prompt: str, model: str, size: str, quality: str) -> str:
    payload = {
        "prompt": prompt,
        "model": model,
        "size": size,
        "quality": quality,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_primary_clause(text: str) -> str:
    cleaned = str(text).strip()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].strip()

    cleaned = re.sub(r"\bwith\b.*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.replace("&quot;", '"').replace("&#x27;", "'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return _truncate(cleaned.strip(" .;,"), 140)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."
