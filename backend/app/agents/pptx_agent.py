"""Agent for PPTX build planning and deterministic output generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.base_agent import BaseAgent
from app.models.generated_visuals import GeneratedVisuals
from app.models.pptx_result import PPTXBuildResult
from app.models.presentation_plan import PresentationPlan
from app.models.speaker_notes import SpeakerNotes
from app.renderers.pptx_renderer import PPTXRenderer


class PPTXBuilderAgent(BaseAgent[PPTXBuildResult]):
    """A10 concrete agent that can validate build plans and create PPTX output."""

    prompt_file = "A10_pptx_builder.txt"
    output_model = PPTXBuildResult

    def build(
        self,
        *,
        presentation_plan: PresentationPlan,
        speaker_notes: SpeakerNotes,
        generated_visuals: GeneratedVisuals,
        output_path: Path,
        asset_map: dict[str, str] | None = None,
    ) -> PPTXBuildResult:
        """Deterministically build an editable PPTX from structured inputs."""
        renderer = PPTXRenderer()
        return renderer.render(
            presentation_plan=presentation_plan,
            speaker_notes=speaker_notes,
            generated_visuals=generated_visuals,
            asset_map=asset_map or {},
            output_path=output_path,
        )

    def plan_and_build(
        self,
        *,
        build_payload: dict[str, Any],
        presentation_plan: PresentationPlan,
        speaker_notes: SpeakerNotes,
        generated_visuals: GeneratedVisuals,
        output_path: Path,
        asset_map: dict[str, str] | None = None,
    ) -> PPTXBuildResult:
        """Optionally run LLM planning before deterministic PPTX building."""
        _ = self.run(build_payload)
        return self.build(
            presentation_plan=presentation_plan,
            speaker_notes=speaker_notes,
            generated_visuals=generated_visuals,
            output_path=output_path,
            asset_map=asset_map,
        )
