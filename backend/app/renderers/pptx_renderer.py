"""Deterministic renderer for first-pass editable PPTX output."""

from __future__ import annotations

import importlib
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.models.generated_visuals import GeneratedVisuals
from app.models.pptx_result import PPTXBuildResult
from app.models.presentation_plan import PresentationPlan
from app.models.speaker_notes import SpeakerNotes


class PPTXRenderer:
    """Render an editable PPTX using python-pptx with simple layouts."""

    def render(
        self,
        *,
        presentation_plan: PresentationPlan,
        speaker_notes: SpeakerNotes,
        generated_visuals: GeneratedVisuals,
        asset_map: dict[str, str],
        output_path: Path,
    ) -> PPTXBuildResult:
        """Write a PPTX file and return a structured build result."""
        try:
            pptx_module = importlib.import_module("pptx")
            presentation_cls = getattr(pptx_module, "Presentation")
        except Exception as exc:
            raise RuntimeError("python-pptx is required for PPTX rendering. Install it with 'pip install python-pptx'.") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        template_path, template_used, template_warnings = self._resolve_template_path(pptx_module)
        presentation = presentation_cls(str(template_path)) if template_path else presentation_cls()
        if template_path is not None:
            self._clear_existing_slides(presentation)

        notes_by_slide = {item.slide_number: item for item in speaker_notes.slide_notes}
        visuals_by_slide = {}
        for item in generated_visuals.generated_visuals:
            visuals_by_slide.setdefault(item.slide_number, []).append(item)

        slide_results = []
        total_slides = len(presentation_plan.slides)
        for slide in presentation_plan.slides:
            pptx_slide = presentation.slides.add_slide(presentation.slide_layouts[1])
            pptx_slide.shapes.title.text = slide.title

            visuals = self._collect_slide_visuals(
                slide_number=slide.slide_number,
                planned_visuals=slide.visuals,
                generated_visuals=visuals_by_slide.get(slide.slide_number, []),
            )

            body_shape = pptx_slide.shapes.placeholders[1]
            self._configure_body_layout(
                body_shape=body_shape,
                has_visual_target=bool(visuals),
                presentation=presentation,
            )
            text_frame = body_shape.text_frame
            text_frame.clear()
            for index, point in enumerate(slide.key_points):
                paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
                paragraph.text = point
            self._apply_bullet_text_downshift(text_frame=text_frame, points=slide.key_points)

            citations = [citation.short_citation for citation in slide.citations]
            self._insert_citations_box(
                pptx_slide=pptx_slide,
                citations=citations,
                presentation=presentation,
            )
            self._insert_page_number(
                pptx_slide=pptx_slide,
                presentation=presentation,
                slide_number=slide.slide_number,
                total_slides=total_slides,
            )

            note = notes_by_slide.get(slide.slide_number)
            if note is not None:
                notes_text = "\n".join(f"- {item}" for item in note.talking_points)
                notes_slide = pptx_slide.notes_slide
                notes_slide.notes_text_frame.text = notes_text

            warnings = []
            assets_used = []
            inserted_visual_count = 0

            for visual in visuals:
                resolved_path = self._resolve_visual_asset_path(
                    visual_id=visual.visual_id,
                    source_artifact_ids=visual.conceptual_basis.grounded_in_source_artifacts,
                    asset_map=asset_map,
                )
                if not resolved_path and visual.provenance_label == "conceptual":
                    inserted = self._insert_conceptual_card(pptx_slide=pptx_slide, visual=visual, slot_index=inserted_visual_count)
                    if inserted:
                        inserted_visual_count += 1
                        assets_used.append(
                            {
                                "asset_id": visual.visual_id,
                                "resolved_path": "generated:inline_conceptual_card",
                            }
                        )
                    else:
                        warnings.append(f"Unable to insert conceptual visual card for {visual.visual_id}")
                        assets_used.append(
                            {
                                "asset_id": visual.visual_id,
                                "resolved_path": "",
                            }
                        )
                    continue

                if not resolved_path:
                    assets_used.append(
                        {
                            "asset_id": visual.visual_id,
                            "resolved_path": "",
                        }
                    )
                    continue

                if self._insert_picture(pptx_slide=pptx_slide, image_path=Path(resolved_path), slot_index=inserted_visual_count):
                    inserted_visual_count += 1
                    assets_used.append(
                        {
                            "asset_id": visual.visual_id,
                            "resolved_path": resolved_path,
                        }
                    )
                else:
                    warnings.append(f"Unable to insert visual image for {visual.visual_id}")
                    assets_used.append(
                        {
                            "asset_id": visual.visual_id,
                            "resolved_path": "",
                        }
                    )

            if visuals and inserted_visual_count == 0:
                warnings.append("No mapped visual images resolved; keeping text-first fallback layout in V1")

            slide_results.append(
                {
                    "slide_number": slide.slide_number,
                    "title": slide.title,
                    "status": "built_with_warning" if warnings else "built",
                    "assets_used": assets_used,
                    "notes_inserted": note is not None,
                    "citations_inserted": bool(citations),
                    "warnings": warnings,
                }
            )

        presentation.save(str(output_path))

        result_payload = {
            "build_status": "success",
            "output": {
                "pptx_path": str(output_path),
                "template_used": template_used,
                "notes_insertion_supported": True,
            },
            "slide_build_results": slide_results,
            "global_warnings": [
                "Visual embedding uses conservative mapped source assets in V1 and falls back to text-first slides when unresolved."
            ]
            + template_warnings,
            "deviations": [],
        }
        return PPTXBuildResult.model_validate(result_payload)

    @staticmethod
    def _resolve_template_path(pptx_module: object) -> tuple[Path | None, str, list[str]]:
        """Resolve a healthy PPTX template path, preferring explicit overrides."""
        template_override = str(os.getenv("PAPER2SLIDES_PPTX_TEMPLATE_PATH", "")).strip()
        if template_override:
            override_path = Path(template_override).expanduser().resolve()
            if not override_path.is_file():
                raise RuntimeError(
                    f"PAPER2SLIDES_PPTX_TEMPLATE_PATH does not exist: {override_path}"
                )
            if not zipfile.is_zipfile(override_path):
                raise RuntimeError(
                    f"PAPER2SLIDES_PPTX_TEMPLATE_PATH is not a valid .pptx package: {override_path}"
                )
            return override_path, str(override_path), [
                "PPTX template override active via PAPER2SLIDES_PPTX_TEMPLATE_PATH."
            ]

        module_file_raw = str(getattr(pptx_module, "__file__", "")).strip()
        if not module_file_raw:
            # Unit tests patch a minimal fake module without __file__. Keep default behavior there.
            return None, "default", []

        module_file = Path(module_file_raw).resolve()
        default_template = module_file.parent / "templates" / "default.pptx"
        if default_template.is_file() and zipfile.is_zipfile(default_template):
            return None, "default", []

        repo_template = PPTXRenderer._find_repo_template()
        if repo_template is not None:
            return repo_template, str(repo_template), [
                "python-pptx default template is invalid; using repository canonical template."
            ]

        fallback_template = PPTXRenderer._find_fallback_template()
        if fallback_template is not None:
            return fallback_template, str(fallback_template), [
                "python-pptx default template is invalid; using discovered fallback template."
            ]

        raise RuntimeError(
            "python-pptx default template is missing or invalid. "
            "Set PAPER2SLIDES_PPTX_TEMPLATE_PATH to a valid .pptx template "
            "or add a canonical template at backend/templates/pptx/default.pptx."
        )

    @staticmethod
    def _repo_template_candidates() -> list[Path]:
        backend_root = Path(__file__).resolve().parents[2]
        return [
            backend_root / "templates" / "pptx" / "default.pptx",
            backend_root / "templates" / "default.pptx",
        ]

    @staticmethod
    def _find_repo_template() -> Path | None:
        for candidate in PPTXRenderer._repo_template_candidates():
            if candidate.is_file() and zipfile.is_zipfile(candidate):
                return candidate.resolve()
        return None

    @staticmethod
    def _find_fallback_template() -> Path | None:
        """Find a valid local PPTX that can act as an emergency template."""
        backend_root = Path(__file__).resolve().parents[2]
        runs_root = backend_root / "runs"
        if not runs_root.is_dir():
            return None

        candidates: list[Path] = []
        patterns = [
            "*/presentation/pptx/deck.pptx",
            "*/output/presentation.pptx",
        ]
        for pattern in patterns:
            candidates.extend(runs_root.glob(pattern))

        candidates = [path for path in candidates if path.is_file() and zipfile.is_zipfile(path)]
        if not candidates:
            return None

        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return candidates[0]

    @staticmethod
    def _clear_existing_slides(presentation: object) -> None:
        """Ensure fallback/custom templates start with no content slides."""
        slides = getattr(presentation, "slides", None)
        slide_id_list = getattr(slides, "_sldIdLst", None)
        part = getattr(presentation, "part", None)
        if slide_id_list is None or part is None:
            return

        while len(slide_id_list):
            r_id = slide_id_list[0].rId
            part.drop_rel(r_id)
            del slide_id_list[0]

    @staticmethod
    def _resolve_visual_asset_path(*, visual_id: str, source_artifact_ids: list[str], asset_map: dict[str, str]) -> str:
        direct = asset_map.get(visual_id)
        if direct:
            return direct

        for artifact_id in source_artifact_ids:
            mapped = asset_map.get(artifact_id)
            if mapped:
                return mapped

        return ""

    @staticmethod
    def _collect_slide_visuals(*, slide_number: int, planned_visuals: list[object], generated_visuals: list[object]) -> list[object]:
        visual_entries: list[object] = list(generated_visuals)

        existing_ids = {
            str(getattr(item, "visual_id", "")).strip()
            for item in visual_entries
            if str(getattr(item, "visual_id", "")).strip()
        }
        existing_artifacts: set[str] = set()
        for item in visual_entries:
            basis = getattr(item, "conceptual_basis", None)
            source_ids = list(getattr(basis, "grounded_in_source_artifacts", []) or [])
            existing_artifacts.update(str(source_id).strip() for source_id in source_ids if str(source_id).strip())

        for index, planned in enumerate(planned_visuals, start=1):
            asset_id = str(getattr(planned, "asset_id", "")).strip()
            visual_type = str(getattr(planned, "visual_type", "")).strip().lower()
            usage_mode = str(getattr(planned, "usage_mode", "")).strip().lower()

            if visual_type == "text_only" or usage_mode == "none" or not asset_id or asset_id.lower() == "none":
                continue
            if asset_id in existing_ids or asset_id in existing_artifacts:
                continue

            conceptual = visual_type == "generated_conceptual" or usage_mode == "conceptual"
            visual_entries.append(
                SimpleNamespace(
                    visual_id=asset_id,
                    slide_number=slide_number,
                    provenance_label="conceptual" if conceptual else "adapted_from_source",
                    conceptual_basis=SimpleNamespace(grounded_in_source_artifacts=[asset_id] if not conceptual else []),
                    visual_spec=SimpleNamespace(main_elements=[str(getattr(planned, "why_this_visual", "")).strip()]),
                )
            )
            existing_ids.add(asset_id)

        return visual_entries

    @staticmethod
    def _apply_bullet_text_downshift(*, text_frame: object, points: list[str]) -> None:
        # Keep all content while reducing overflow risk on dense slides.
        max_len = max((len(point) for point in points), default=0)
        count = len(points)
        font_size = 18
        if count >= 6 or max_len >= 140:
            font_size = 16
        if count >= 8 or max_len >= 220:
            font_size = 14
        if count >= 10 or max_len >= 320:
            font_size = 12

        setattr(text_frame, "word_wrap", True)
        font_size_value = PPTXRenderer._to_pptx_points(font_size)
        for paragraph in getattr(text_frame, "paragraphs", []):
            font = getattr(paragraph, "font", None)
            if font is None:
                continue
            try:
                font.size = font_size_value
            except Exception:
                continue

    @staticmethod
    def _configure_body_layout(*, body_shape: object, has_visual_target: bool, presentation: object) -> None:
        slide_width = int(getattr(presentation, "slide_width", 12_192_000))
        slide_height = int(getattr(presentation, "slide_height", 6_858_000))

        left_margin = 460_000
        top = 1_700_000
        bottom_reserved = 1_240_000
        height = max(2_000_000, slide_height - top - bottom_reserved)

        if has_visual_target:
            width = max(3_800_000, int(slide_width * 0.45))
        else:
            width = max(6_500_000, slide_width - (left_margin * 2))

        try:
            body_shape.left = left_margin
            body_shape.top = top
            body_shape.width = width
            body_shape.height = height
        except Exception:
            return

    @staticmethod
    def _insert_citations_box(*, pptx_slide: object, citations: list[str], presentation: object) -> None:
        lines = [citation.strip() for citation in citations if citation.strip()]
        if not lines:
            text = "Citations:"
        else:
            text = "Citations:\n" + "\n".join(f"- {line}" for line in lines)

        slide_width = int(getattr(presentation, "slide_width", 12_192_000))
        slide_height = int(getattr(presentation, "slide_height", 6_858_000))
        left_margin = 260_000
        right_margin = 1_260_000
        bottom_margin = 360_000
        line_count = max(1, len(lines) + 1)
        box_height = min(1_000_000, 180_000 + (line_count * 110_000))
        width = max(6_200_000, slide_width - left_margin - right_margin)
        top = max(0, slide_height - box_height - bottom_margin)
        box = pptx_slide.shapes.add_textbox(left=left_margin, top=top, width=width, height=box_height)
        box.text_frame.text = text
        setattr(box.text_frame, "word_wrap", True)

        font_size_value = PPTXRenderer._to_pptx_points(11)
        for paragraph in getattr(box.text_frame, "paragraphs", []):
            font = getattr(paragraph, "font", None)
            if font is None:
                continue
            try:
                font.size = font_size_value
            except Exception:
                continue

    @staticmethod
    def _to_pptx_points(size_pt: int) -> object:
        try:
            util_module = importlib.import_module("pptx.util")
            return util_module.Pt(size_pt)
        except Exception:
            return size_pt

    @staticmethod
    def _insert_picture(*, pptx_slide: object, image_path: Path, slot_index: int) -> bool:
        if not image_path.is_file():
            return False

        # Keep deterministic image placement so decks are consistent across runs.
        left = 6_050_000
        top = 1_550_000 + (slot_index * 180_000)
        width = 5_500_000
        height = 3_250_000

        try:
            pptx_slide.shapes.add_picture(str(image_path), left, top, width=width, height=height)
            return True
        except Exception:
            return False

    @staticmethod
    def _insert_conceptual_card(*, pptx_slide: object, visual: object, slot_index: int) -> bool:
        """Insert a deterministic conceptual diagram card when no image asset exists."""
        left = 6_050_000
        top = 1_550_000 + (slot_index * 1_900_000)
        width = 5_500_000
        height = 1_850_000

        elements = list(getattr(getattr(visual, "visual_spec", object()), "main_elements", []))[:4]
        lines = [f"- {str(item)}" for item in elements if str(item).strip()]
        if not lines:
            lines = ["- Concept overview", "- Key mechanism", "- Implication"]

        header = f"{getattr(visual, 'visual_id', 'GV')} conceptual diagram"
        body = "\n".join(lines)
        text = f"{header}\n{body}"

        try:
            box = pptx_slide.shapes.add_textbox(left=left, top=top, width=width, height=height)
            box.text_frame.text = text
            return True
        except Exception:
            return False

    @staticmethod
    def _insert_page_number(*, pptx_slide: object, presentation: object, slide_number: int, total_slides: int) -> None:
        slide_width = int(getattr(presentation, "slide_width", 12_192_000))
        slide_height = int(getattr(presentation, "slide_height", 6_858_000))
        width = 900_000
        height = 240_000
        right_margin = 220_000
        bottom_margin = 120_000

        left = max(0, slide_width - width - right_margin)
        top = max(0, slide_height - height - bottom_margin)

        try:
            box = pptx_slide.shapes.add_textbox(left=left, top=top, width=width, height=height)
            box.text_frame.text = f"{slide_number} / {total_slides}"
        except Exception:
            return
