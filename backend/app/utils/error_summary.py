"""Compact exception formatting helpers for run manifests and logs."""

from __future__ import annotations

from typing import Any


def _truncate_single_line(value: str, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_field_list(fields: list[str], *, max_items: int = 4) -> str:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in fields:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(cleaned)

    if not deduped:
        return ""

    shown = deduped[:max_items]
    suffix = "" if len(deduped) <= max_items else f", +{len(deduped) - max_items} more"
    return ", ".join(shown) + suffix


def _try_summarize_validation_error(exc: Exception) -> str | None:
    errors_method = getattr(exc, "errors", None)
    if not callable(errors_method):
        return None

    try:
        issues = errors_method()
    except Exception:
        return None

    if not isinstance(issues, list) or not issues:
        return None

    missing_fields: list[str] = []
    extra_fields: list[str] = []
    other_fields: list[str] = []

    for item in issues:
        if not isinstance(item, dict):
            continue

        loc_value = item.get("loc", [])
        if isinstance(loc_value, (list, tuple)):
            field = ".".join(str(part) for part in loc_value if str(part).strip())
        else:
            field = str(loc_value or "")
        field = field or "(root)"

        issue_type = str(item.get("type", "") or "")
        if issue_type == "missing":
            missing_fields.append(field)
        elif issue_type == "extra_forbidden":
            extra_fields.append(field)
        else:
            other_fields.append(field)

    model_name = str(getattr(exc, "title", "") or type(exc).__name__)
    parts: list[str] = []

    missing_summary = _format_field_list(missing_fields)
    if missing_summary:
        parts.append(f"missing fields: {missing_summary}")

    extra_summary = _format_field_list(extra_fields)
    if extra_summary:
        parts.append(f"unexpected fields: {extra_summary}")

    other_summary = _format_field_list(other_fields)
    if other_summary:
        parts.append(f"other invalid fields: {other_summary}")

    detail = "; ".join(parts) if parts else "schema mismatch"
    return f"{model_name} validation failed ({len(issues)} issue(s)): {detail}"


def summarize_exception_for_logs(exc: Exception, *, limit: int = 320) -> str:
    """Return a concise, single-line exception summary suitable for manifests."""
    validation_summary = _try_summarize_validation_error(exc)
    if validation_summary:
        return _truncate_single_line(validation_summary, limit=limit)

    raw = _truncate_single_line(str(exc), limit=limit)
    if raw:
        return raw

    return f"{type(exc).__name__} raised with no message"
