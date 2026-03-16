"""Deterministic conceptual visual materialization helpers."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any


CANVAS_WIDTH = 1360
CANVAS_HEIGHT = 768


def render_conceptual_svg(*, generated: Any, assets_dir: Path) -> Path:
    """Render a concrete SVG visual from generated visual specs."""
    visual_kind = str(getattr(generated, "visual_kind", "other"))
    raw_visual_id = str(getattr(generated, "visual_id", "GV"))
    svg_token = "".join(ch if ch.isalnum() else "-" for ch in raw_visual_id) or "GV"
    visual_id = html.escape(raw_visual_id)
    title = html.escape(str(getattr(generated, "slide_title", "Conceptual Visual")))
    purpose = str(getattr(generated, "visual_purpose", "Explain the key concept"))

    spec = getattr(generated, "visual_spec", None)
    main_elements = _safe_list(
        getattr(spec, "main_elements", []),
        fallback=["Concept A", "Concept B", "Concept C"],
    )
    labels = _safe_list(getattr(spec, "labels_or_text", []), fallback=[])
    theme = _theme_for_kind(visual_kind)

    if visual_kind == "workflow":
        body = _build_workflow_markup(main_elements, theme)
    elif visual_kind == "timeline":
        body = _build_timeline_markup(main_elements, theme)
    elif visual_kind == "comparison_framework":
        body = _build_comparison_markup(main_elements, theme)
    elif visual_kind == "concept_map":
        body = _build_concept_map_markup(main_elements, theme)
    else:
        body = _build_cards_markup(main_elements, theme)

    label_markup = _build_label_badges(labels, theme)
    svg_markup = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}">'
        '<defs>'
        f'<linearGradient id="bg-{svg_token}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{theme["bg_start"]}"/>'
        f'<stop offset="100%" stop-color="{theme["bg_end"]}"/>'
        '</linearGradient>'
        f'<filter id="soft-shadow-{svg_token}" x="-20%" y="-20%" width="140%" height="140%">'
        '<feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#0f172a" flood-opacity="0.12"/>'
        '</filter>'
        '</defs>'
        f'<rect x="0" y="0" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="url(#bg-{svg_token})"/>'
        '<circle cx="-40" cy="140" r="190" fill="#ffffff" opacity="0.35"/>'
        '<circle cx="1240" cy="730" r="280" fill="#ffffff" opacity="0.28"/>'
        f'<rect x="34" y="28" width="1292" height="712" rx="30" fill="#ffffff" stroke="#dbe4ee" stroke-width="2" filter="url(#soft-shadow-{svg_token})"/>'
        f'<text x="70" y="82" font-size="34" font-weight="700" fill="{theme["title"]}">{visual_id} - {html.escape(visual_kind.replace("_", " ").title())}</text>'
        f'<text x="70" y="118" font-size="21" font-weight="600" fill="{theme["subtitle"]}">{title}</text>'
        + _text_multiline(content=purpose, x=70, y=148, max_chars_per_line=92, font_size=16, fill=theme["muted"], max_lines=2)
        + f'<rect x="1072" y="44" width="214" height="40" rx="20" fill="{theme["badge_bg"]}"/>'
        + f'<text x="1098" y="70" font-size="15" font-weight="700" fill="{theme["badge_text"]}">Conceptual Model</text>'
        + '<line x1="68" y1="174" x2="1292" y2="174" stroke="#e2e8f0" stroke-width="2"/>'
        + body
        + label_markup
        + '</svg>'
    )

    target = assets_dir / f"{raw_visual_id}.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg_markup, encoding="utf-8")
    return target


def _safe_list(values: Any, *, fallback: list[str]) -> list[str]:
    if not isinstance(values, list):
        return fallback
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    return cleaned or fallback


def _theme_for_kind(kind: str) -> dict[str, str]:
    key = kind.strip().lower()
    themes = {
        "workflow": {
            "bg_start": "#e7f0ff",
            "bg_end": "#ecfeff",
            "title": "#0b3b75",
            "subtitle": "#1f4f88",
            "muted": "#465f7d",
            "accent": "#1d4ed8",
            "accent_soft": "#dbeafe",
            "node_fill": "#eef4ff",
            "node_stroke": "#9fbef7",
            "badge_bg": "#dbeafe",
            "badge_text": "#1e3a8a",
        },
        "timeline": {
            "bg_start": "#ecfeff",
            "bg_end": "#ecfccb",
            "title": "#0f766e",
            "subtitle": "#115e59",
            "muted": "#3f6765",
            "accent": "#0f766e",
            "accent_soft": "#ccfbf1",
            "node_fill": "#f0fdfa",
            "node_stroke": "#5eead4",
            "badge_bg": "#ccfbf1",
            "badge_text": "#115e59",
        },
        "comparison_framework": {
            "bg_start": "#fff7ed",
            "bg_end": "#eff6ff",
            "title": "#7c2d12",
            "subtitle": "#9a3412",
            "muted": "#6b4d38",
            "accent": "#ea580c",
            "accent_soft": "#ffedd5",
            "node_fill": "#fff7ed",
            "node_stroke": "#fdba74",
            "badge_bg": "#ffedd5",
            "badge_text": "#9a3412",
        },
        "concept_map": {
            "bg_start": "#eef2ff",
            "bg_end": "#f0f9ff",
            "title": "#1e3a8a",
            "subtitle": "#3730a3",
            "muted": "#525f7f",
            "accent": "#4338ca",
            "accent_soft": "#e0e7ff",
            "node_fill": "#f5f7ff",
            "node_stroke": "#a5b4fc",
            "badge_bg": "#e0e7ff",
            "badge_text": "#3730a3",
        },
    }
    return themes.get(
        key,
        {
            "bg_start": "#eff6ff",
            "bg_end": "#f0fdfa",
            "title": "#0f172a",
            "subtitle": "#334155",
            "muted": "#475569",
            "accent": "#0f766e",
            "accent_soft": "#dcfce7",
            "node_fill": "#f8fafc",
            "node_stroke": "#94a3b8",
            "badge_bg": "#dcfce7",
            "badge_text": "#166534",
        },
    )


def _build_workflow_markup(items: list[str], theme: dict[str, str]) -> str:
    steps = (items or ["Input", "Transform", "Evaluate", "Output"])[:5]
    top = 238
    step_width = 210
    gap = 36
    total_width = (len(steps) * step_width) + ((len(steps) - 1) * gap)
    start_x = max(64, int((CANVAS_WIDTH - total_width) / 2))
    parts = []
    parts.append(
        '<rect x="66" y="204" width="1228" height="396" rx="24" fill="#f8fbff" stroke="#dbe7f4" stroke-width="2"/>'
    )
    y = top
    for idx, label in enumerate(steps):
        x = start_x + idx * (step_width + gap)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{step_width}" height="128" rx="18" fill="{theme["node_fill"]}" stroke="{theme["node_stroke"]}" stroke-width="2"/>'
        )
        parts.append(f'<text x="{x + 18}" y="{y + 34}" font-size="14" font-weight="700" fill="{theme["accent"]}">Step {idx + 1}</text>')
        parts.append(
            _text_multiline(
                content=label,
                x=x + 18,
                y=y + 62,
                max_chars_per_line=18,
                font_size=18,
                fill="#0f172a",
                max_lines=3,
                line_height=24,
            )
        )
        if idx < len(steps) - 1:
            next_x = start_x + (idx + 1) * (step_width + gap)
            line_y = y + 64
            parts.append(
                f'<line x1="{x + step_width}" y1="{line_y}" x2="{next_x - 10}" y2="{line_y}" stroke="{theme["accent"]}" stroke-width="4"/>'
            )
            parts.append(
                f'<polygon points="{next_x - 20},{line_y - 9} {next_x - 6},{line_y} {next_x - 20},{line_y + 9}" fill="{theme["accent"]}"/>'
            )

    parts.append(
        f'<rect x="94" y="540" width="1170" height="44" rx="12" fill="{theme["accent_soft"]}"/>'
    )
    parts.append(
        f'<text x="116" y="568" font-size="17" font-weight="600" fill="{theme["badge_text"]}">Flow highlights cause-and-effect progression across the slide narrative.</text>'
    )
    return "".join(parts)


def _build_timeline_markup(items: list[str], theme: dict[str, str]) -> str:
    points = (items or ["Baseline", "Shift", "Response", "Outcome"])[:6]
    x_start = 156
    gap = 200
    y_line = 378
    parts = [
        '<rect x="78" y="242" width="1200" height="298" rx="24" fill="#f8fbff" stroke="#dbe7f4" stroke-width="2"/>',
        f'<line x1="138" y1="{y_line}" x2="1218" y2="{y_line}" stroke="{theme["accent"]}" stroke-width="6"/>',
    ]
    for idx, label in enumerate(points):
        x = x_start + (idx * gap)
        parts.append(
            f'<circle cx="{x}" cy="{y_line}" r="20" fill="{theme["accent_soft"]}" stroke="{theme["accent"]}" stroke-width="4"/>'
        )
        parts.append(f'<circle cx="{x}" cy="{y_line}" r="6" fill="{theme["accent"]}"/>')
        offset = -74 if idx % 2 == 0 else 58
        parts.append(
            _text_multiline(
                content=label,
                x=x - 80,
                y=y_line + offset,
                max_chars_per_line=16,
                font_size=16,
                fill="#12343b",
                max_lines=2,
                line_height=20,
            )
        )
    return "".join(parts)


def _build_comparison_markup(items: list[str], theme: dict[str, str]) -> str:
    left = html.escape(items[0] if items else "Approach A")
    right = html.escape(items[1] if len(items) > 1 else "Approach B")
    middle = html.escape(items[2] if len(items) > 2 else "Trade-offs")
    left_note = html.escape(items[3] if len(items) > 3 else "Strengths")
    right_note = html.escape(items[4] if len(items) > 4 else "Limitations")
    return (
        '<rect x="88" y="204" width="1184" height="408" rx="24" fill="#f8fbff" stroke="#dbe7f4" stroke-width="2"/>'
        '<rect x="136" y="246" width="470" height="318" rx="22" fill="#fff7ed" stroke="#fdba74" stroke-width="2"/>'
        '<rect x="754" y="246" width="470" height="318" rx="22" fill="#eff6ff" stroke="#93c5fd" stroke-width="2"/>'
        f'<text x="166" y="292" font-size="30" font-weight="700" fill="#9a3412">{left}</text>'
        f'<text x="784" y="292" font-size="30" font-weight="700" fill="#1e3a8a">{right}</text>'
        + _text_multiline(content=left_note, x=166, y=334, max_chars_per_line=32, font_size=20, fill="#7c2d12", max_lines=3, line_height=28)
        + _text_multiline(content=right_note, x=784, y=334, max_chars_per_line=32, font_size=20, fill="#1e3a8a", max_lines=3, line_height=28)
        + f'<line x1="622" y1="402" x2="738" y2="402" stroke="{theme["accent"]}" stroke-width="4"/>'
        + f'<polygon points="732,394 748,402 732,410" fill="{theme["accent"]}"/>'
        + f'<text x="620" y="378" font-size="17" font-weight="600" fill="#475569">{middle}</text>'
    )


def _build_concept_map_markup(items: list[str], theme: dict[str, str]) -> str:
    anchor, spokes = _derive_concept_map_labels(items)
    positions = [(256, 250), (680, 228), (1088, 250), (328, 542), (1038, 542)]
    parts = [
        '<rect x="84" y="206" width="1192" height="412" rx="24" fill="#f8fbff" stroke="#dbe7f4" stroke-width="2"/>',
        f'<circle cx="680" cy="390" r="126" fill="{theme["accent_soft"]}" stroke="{theme["accent"]}" stroke-width="3"/>',
        _text_multiline(content=anchor, x=610, y=378, max_chars_per_line=14, font_size=23, fill=theme["badge_text"], max_lines=3, line_height=28),
    ]
    for idx, spoke in enumerate(spokes):
        x, y = positions[idx]
        parts.append(
            f'<rect x="{x - 116}" y="{y - 52}" width="232" height="104" rx="16" fill="{theme["node_fill"]}" stroke="{theme["node_stroke"]}" stroke-width="2"/>'
        )
        parts.append(
            _text_multiline(
                content=spoke,
                x=x - 98,
                y=y - 6,
                max_chars_per_line=18,
                font_size=18,
                fill="#1f2937",
                max_lines=3,
                line_height=22,
            )
        )
        parts.append(f'<line x1="680" y1="390" x2="{x}" y2="{y}" stroke="#6b7280" stroke-width="3"/>')
    return "".join(parts)


def _build_cards_markup(items: list[str], theme: dict[str, str]) -> str:
    cards = (items or ["Theme", "Signal", "Interpretation", "Action"])[:6]
    parts = []
    x = 96
    y = 214
    parts.append('<rect x="78" y="198" width="1200" height="424" rx="24" fill="#f8fbff" stroke="#dbe7f4" stroke-width="2"/>')
    for idx, label in enumerate(cards):
        col = idx % 3
        row = idx // 3
        px = x + (col * 386)
        py = y + (row * 192)
        parts.append(
            f'<rect x="{px}" y="{py}" width="356" height="160" rx="16" fill="{theme["node_fill"]}" stroke="{theme["node_stroke"]}" stroke-width="2"/>'
        )
        parts.append(f'<text x="{px + 18}" y="{py + 34}" font-size="13" font-weight="700" fill="{theme["accent"]}">Key Point {idx + 1}</text>')
        parts.append(
            _text_multiline(
                content=label,
                x=px + 18,
                y=py + 66,
                max_chars_per_line=22,
                font_size=20,
                fill="#111827",
                max_lines=3,
                line_height=26,
            )
        )
    return "".join(parts)


def _build_label_badges(labels: list[str], theme: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = []
    x = 70
    y = 680
    for label in labels[:4]:
        text = _truncate_text(_extract_primary_clause(label), max_chars=36)
        if not text:
            continue
        safe_text = html.escape(text)
        width = max(110, min(260, 18 + (len(text) * 8)))
        if x + width > 1290:
            break
        parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="34" rx="16" fill="{theme["accent_soft"]}"/>')
        parts.append(f'<text x="{x + 12}" y="{y + 22}" font-size="14" font-weight="600" fill="{theme["badge_text"]}">{safe_text}</text>')
        x += width + 10
    return "".join(parts)


def _text_multiline(
    *,
    content: str,
    x: int,
    y: int,
    max_chars_per_line: int,
    font_size: int,
    fill: str,
    max_lines: int,
    line_height: int = 20,
) -> str:
    lines = _wrap_text(content, max_chars_per_line=max_chars_per_line, max_lines=max_lines)
    if not lines:
        return ""

    tspans = []
    for idx, line in enumerate(lines):
        dy = 0 if idx == 0 else line_height
        tspans.append(f'<tspan x="{x}" dy="{dy}">{html.escape(line)}</tspan>')
    return f'<text x="{x}" y="{y}" font-size="{font_size}" fill="{fill}">{"".join(tspans)}</text>'


def _wrap_text(content: str, *, max_chars_per_line: int, max_lines: int) -> list[str]:
    words = content.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars_per_line:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break

    if len(lines) < max_lines and current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if len(lines) == max_lines and len(" ".join(words)) > sum(len(line) for line in lines):
        if len(lines[-1]) > 3:
            lines[-1] = lines[-1][:-3].rstrip() + "..."
    return lines


def _derive_concept_map_labels(items: list[str]) -> tuple[str, list[str]]:
    normalized = [_extract_primary_clause(item) for item in items if item and str(item).strip()]
    if not normalized:
        return "Core Concept", ["Dimension A", "Dimension B"]

    anchor = _truncate_text(normalized[0], max_chars=46)
    spokes = [_truncate_text(item, max_chars=44) for item in normalized[1:6] if item]
    if not spokes:
        spokes = ["Dimension A", "Dimension B"]
    return anchor, spokes


def _extract_primary_clause(text: str) -> str:
    cleaned = str(text).strip()
    if not cleaned:
        return ""

    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].strip()

    cleaned = re.sub(r"\bwith\b.*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip(" .;,")

    if len(cleaned) >= 2 and cleaned[0] in {'"', "'"} and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1].strip()

    cleaned = cleaned.replace("&quot;", '"').replace("&#x27;", "'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _truncate_text(text: str, *, max_chars: int) -> str:
    value = str(text).strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."