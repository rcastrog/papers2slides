"""Deterministic renderer for first-pass Reveal-style HTML output."""

from __future__ import annotations

import html
import importlib
import re
import shutil
from pathlib import Path
from typing import Any

from app.models.generated_visuals import GeneratedVisuals
from app.models.presentation_plan import PresentationPlan
from app.models.reveal_result import RevealRenderResult
from app.models.speaker_notes import SpeakerNotes
from app.utils.conceptual_visual_factory import render_conceptual_svg


class RevealRenderer:
    """Render slides into a simple HTML deck under a reveal output folder."""

    def render(
        self,
        *,
        presentation_plan: PresentationPlan,
        speaker_notes: SpeakerNotes,
        generated_visuals: GeneratedVisuals,
        asset_map: dict[str, str],
        output_dir: Path,
    ) -> RevealRenderResult:
        """Write index.html and assets folder, then return a structured render result."""
        output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        notes_by_slide = {item.slide_number: item for item in speaker_notes.slide_notes}
        generated_visuals_by_slide = {}
        generated_visuals_by_id = {}
        for item in generated_visuals.generated_visuals:
            generated_visuals_by_slide.setdefault(item.slide_number, []).append(item)
            generated_visuals_by_id[item.visual_id] = item

        slide_results = []
        slide_html_parts = []

        for slide in presentation_plan.slides:
            note = notes_by_slide.get(slide.slide_number)
            generated_for_slide = generated_visuals_by_slide.get(slide.slide_number, [])
            citations = [citation.short_citation for citation in slide.citations]
            citation_rows = [
                {
                    "text": citation.short_citation,
                    "purpose": citation.citation_purpose,
                    "slide_title": slide.title,
                    "slide_objective": slide.objective,
                    "key_points": list(slide.key_points),
                }
                for citation in slide.citations
            ]

            visual_blocks = []
            assets_used = []
            warnings = []
            rendered_ids: set[str] = set()

            for planned_visual in slide.visuals:
                asset_id = planned_visual.asset_id.strip()
                if asset_id.lower() == "none" or planned_visual.visual_type == "text_only":
                    continue

                rendered_ids.add(asset_id)
                origin = planned_visual.source_origin if planned_visual.source_origin != "none" else "generated"

                resolved_asset = (
                    asset_map.get(asset_id)
                    or self._discover_asset_path(asset_id=asset_id, source_origin=origin, output_dir=output_dir)
                )
                display_src = self._prepare_asset_for_html(
                    resolved_asset=resolved_asset,
                    output_dir=output_dir,
                    assets_dir=assets_dir,
                )

                if not display_src and origin == "generated":
                    generated = generated_visuals_by_id.get(asset_id)
                    if generated is not None:
                        generated_path = render_conceptual_svg(generated=generated, assets_dir=assets_dir)
                        display_src = generated_path.relative_to(output_dir).as_posix()
                        resolved_asset = str(generated_path.resolve())

                if display_src:
                    provenance_suffix = " (conceptual AI-generated)" if origin == "generated" else ""
                    visual_blocks.append(
                        (
                            '<figure class="visual-frame">'
                            f'<img src="{html.escape(display_src)}" alt="{html.escape(planned_visual.why_this_visual)}" />'
                            f'<figcaption>{html.escape(asset_id)} - {html.escape(planned_visual.why_this_visual + provenance_suffix)}</figcaption>'
                            "</figure>"
                        )
                    )
                else:
                    warnings.append(f"Missing asset for visual {asset_id}")
                    visual_blocks.append(
                        (
                            '<figure class="visual-frame placeholder">'
                            f'<div class="visual-badge">{html.escape(asset_id)}</div>'
                            f'<p>{html.escape(planned_visual.why_this_visual)}</p>'
                            "</figure>"
                        )
                    )

                assets_used.append(
                    {
                        "asset_id": asset_id,
                        "resolved_path": resolved_asset or "",
                        "source_origin": origin,
                    }
                )

            for generated in generated_for_slide:
                if generated.visual_id in rendered_ids:
                    continue

                resolved_asset = (
                    asset_map.get(generated.visual_id)
                    or self._discover_asset_path(asset_id=generated.visual_id, source_origin="generated", output_dir=output_dir)
                )
                display_src = self._prepare_asset_for_html(
                    resolved_asset=resolved_asset,
                    output_dir=output_dir,
                    assets_dir=assets_dir,
                )
                if not display_src:
                    generated_path = render_conceptual_svg(generated=generated, assets_dir=assets_dir)
                    display_src = generated_path.relative_to(output_dir).as_posix()
                    resolved_asset = str(generated_path.resolve())

                visual_blocks.append(
                    (
                        '<figure class="visual-frame">'
                        f'<img src="{html.escape(display_src)}" alt="{html.escape(generated.visual_purpose)}" />'
                        f'<figcaption>{html.escape(generated.visual_id)} - conceptual visual (conceptual AI-generated)</figcaption>'
                        "</figure>"
                    )
                )
                assets_used.append(
                    {
                        "asset_id": generated.visual_id,
                        "resolved_path": resolved_asset or "",
                        "source_origin": "generated",
                    }
                )

            notes_block = ""
            if note is not None:
                note_items = "".join(f"<li>{html.escape(point)}</li>" for point in note.talking_points)
                notes_block = f'<aside class="notes"><ul>{note_items}</ul></aside>'

            key_points_html = "".join(f"<li>{html.escape(point)}</li>" for point in slide.key_points)
            citations_html = "".join(
                (
                    '<span class="citation-chip" '
                    f'title="{html.escape("Why cited: " + self._purpose_label(item))}">'
                    f'{html.escape(str(item.get("text", "")))}'
                    "</span>"
                )
                for item in citation_rows
            )
            citation_why_details = ""
            if citation_rows:
                list_items = "".join(
                    (
                        "<li>"
                        f'{html.escape(str(item.get("text", "")))}: '
                        f'{html.escape(self._purpose_label(item))}'
                        "</li>"
                    )
                    for item in citation_rows
                )
                citation_why_details = (
                    '<details class="citation-why">'
                    '<summary>Why cited</summary>'
                    f"<ul>{list_items}</ul>"
                    "</details>"
                )
            visuals_html = "".join(visual_blocks)

            slide_html_parts.append(
                f"""
<section class=\"slide\">
  <h2 class=\"slide-title\">{html.escape(slide.title)}</h2>
  <div class=\"slide-body\">
    <ul>{key_points_html}</ul>
    <div class=\"visuals\">{visuals_html}</div>
  </div>
    <footer>
        <div class="citation-row">{citations_html}</div>
        {citation_why_details}
    </footer>
  {notes_block}
</section>
"""
            )

            status = "rendered"
            if warnings:
                status = "rendered_with_warning"
            elif visual_blocks and not assets_used:
                status = "rendered_with_warning"

            slide_results.append(
                {
                    "slide_number": slide.slide_number,
                    "title": slide.title,
                    "status": status,
                    "assets_used": assets_used,
                    "citations_rendered": citations,
                    "notes_attached": note is not None,
                    "warnings": warnings,
                }
            )

        html_output = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html.escape(presentation_plan.deck_metadata.title)}</title>
  <style>
        :root {{
            --ink: #102a43;
            --ink-soft: #486581;
            --surface: #ffffff;
            --accent: #0f766e;
            --accent-soft: #d1fae5;
            --frame: #d9e2ec;
        }}
        body {{
            font-family: "Segoe UI", "Helvetica Neue", sans-serif;
            margin: 0;
            color: var(--ink);
            background: radial-gradient(circle at 20% 0%, #e0f2fe 0%, #f8fafc 55%, #eef2ff 100%);
        }}
        main {{ max-width: 1100px; margin: 0 auto; padding: 28px; }}
        .slide {{
            background: var(--surface);
            border: 1px solid var(--frame);
            border-radius: 16px;
            margin-bottom: 20px;
            padding: 22px;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
        }}
        .slide-title {{ margin: 0 0 14px 0; }}
        .slide-body {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }}
        .slide-body ul {{ margin: 0; padding-left: 20px; color: var(--ink-soft); line-height: 1.5; }}
        .visuals {{ display: grid; gap: 10px; }}
        .visual-frame {{
            margin: 0;
            border: 1px solid var(--frame);
            border-radius: 12px;
            background: #f8fafc;
            overflow: hidden;
            position: relative;
        }}
        .visual-frame img {{ width: 100%; height: 220px; object-fit: contain; display: block; background: #fff; }}
        .visual-frame figcaption {{
            padding: 10px;
            font-size: 0.82rem;
            color: var(--ink-soft);
            border-top: 1px solid var(--frame);
            background: #fdfefe;
        }}
        .visual-frame.placeholder {{
            min-height: 220px;
            display: grid;
            align-content: center;
            justify-items: center;
            gap: 8px;
            background: repeating-linear-gradient(-45deg, #eff6ff, #eff6ff 12px, #dbeafe 12px, #dbeafe 24px);
        }}
        .visual-badge {{
            background: var(--accent-soft);
            color: var(--accent);
            border-radius: 999px;
            padding: 6px 12px;
            font-weight: 600;
            font-size: 0.8rem;
        }}
        footer {{ margin-top: 12px; font-size: 0.8rem; color: var(--ink-soft); }}
        .citation-row {{ display: flex; flex-wrap: wrap; gap: 6px; }}
        .citation-chip {{
            display: inline-flex;
            align-items: center;
            border: 1px solid #cbd5e1;
            border-radius: 999px;
            padding: 2px 8px;
            background: #f8fafc;
            color: #334155;
            font-size: 0.76rem;
            cursor: help;
        }}
        .citation-why {{ margin-top: 6px; }}
        .citation-why summary {{ cursor: pointer; color: #0f766e; font-weight: 600; }}
        .citation-why ul {{ margin: 6px 0 0 16px; padding: 0; }}
        .citation-why li {{ margin-bottom: 4px; color: #486581; }}
        .notes {{ margin-top: 12px; border-top: 1px dashed #bcccdc; padding-top: 10px; color: #334e68; }}
        @media (max-width: 900px) {{
            main {{ padding: 16px; }}
            .slide {{ padding: 16px; }}
            .slide-body {{ grid-template-columns: 1fr; }}
            .visual-frame img {{ height: 180px; }}
        }}
  </style>
</head>
<body>
  <main>
    {''.join(slide_html_parts)}
  </main>
</body>
</html>
"""

        entry_html_path = output_dir / "index.html"
        entry_html_path.write_text(html_output, encoding="utf-8")

        result_payload = {
            "render_status": "success",
            "output": {
                "reveal_root_path": str(output_dir),
                "entry_html_path": str(entry_html_path),
                "assets_directory": str(assets_dir),
                "theme_name": "minimal-v1",
            },
            "slide_render_results": slide_results,
            "global_warnings": ["Output is deterministic HTML and does not include full reveal.js runtime in V1."],
            "deviations": [],
        }
        return RevealRenderResult.model_validate(result_payload)

    @staticmethod
    def _discover_asset_path(*, asset_id: str, source_origin: str, output_dir: Path) -> str:
        extensions = (".png", ".jpg", ".jpeg", ".webp", ".svg")
        run_root: Path | None = None
        if len(output_dir.parents) >= 2:
            run_root = output_dir.parents[1]

        if run_root is None:
            return ""

        search_roots = []
        if source_origin == "source_paper":
            search_roots.append(run_root / "source_paper")
        elif source_origin == "reference_paper":
            search_roots.append(run_root / "references")
        else:
            search_roots.extend((run_root / "presentation" / "assets", run_root / "source_paper"))

        for root in search_roots:
            for extension in extensions:
                candidate = root / f"{asset_id}{extension}"
                if candidate.is_file():
                    return str(candidate)
        return ""

    @staticmethod
    def _purpose_label(citation_row: dict[str, Any]) -> str:
        purpose = str(citation_row.get("purpose", "contextual_reference")).strip().lower()
        slide_title = str(citation_row.get("slide_title", "")).strip()
        slide_objective = str(citation_row.get("slide_objective", "")).strip()
        key_points = citation_row.get("key_points", [])
        claim_anchor = ""
        if isinstance(key_points, list):
            for point in key_points:
                text = str(point or "").strip()
                if text:
                    claim_anchor = text.rstrip(".")
                    break

        subject = slide_objective or claim_anchor or slide_title or "the slide's main point"
        subject = re.sub(r"\s+", " ", subject).strip()
        if len(subject) > 120:
            subject = subject[:117].rstrip() + "..."

        if purpose == "source_of_claim":
            return f"supports the claim that {subject}"
        if purpose == "method_background":
            return f"provides method background for {subject}"
        if purpose == "attribution":
            return f"attributes source details related to {subject}"
        return f"provides context for {subject}"

    @staticmethod
    def _prepare_asset_for_html(*, resolved_asset: str, output_dir: Path, assets_dir: Path) -> str:
        if not resolved_asset:
            return ""

        candidate = Path(resolved_asset)
        if not candidate.is_file():
            return ""

        candidate = candidate.resolve()
        output_dir = output_dir.resolve()
        assets_dir = assets_dir.resolve()

        web_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
        if candidate.suffix.lower() not in web_exts:
            converted = RevealRenderer._convert_to_png_if_possible(candidate=candidate, assets_dir=assets_dir)
            if converted is not None:
                candidate = converted
            else:
                return ""

        try:
            return candidate.relative_to(output_dir).as_posix()
        except ValueError:
            target_name = candidate.name
            copied_target = assets_dir / target_name
            if not copied_target.exists():
                shutil.copy2(candidate, copied_target)
            return copied_target.relative_to(output_dir).as_posix()

    @staticmethod
    def _convert_to_png_if_possible(*, candidate: Path, assets_dir: Path) -> Path | None:
        """Attempt to convert a non-web image to PNG for Reveal compatibility."""
        try:
            pil_image = importlib.import_module("PIL.Image")
        except Exception:
            return None

        target = assets_dir / f"{candidate.stem}.png"
        if target.exists():
            return target

        try:
            with pil_image.open(candidate) as image:
                if str(getattr(image, "mode", "")).upper() not in {"RGB", "RGBA"}:
                    image = image.convert("RGB")
                image.save(target, format="PNG")
            return target
        except Exception:
            return None

