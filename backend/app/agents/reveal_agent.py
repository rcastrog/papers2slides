"""Agent for Reveal.js render planning and deterministic output generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.base_agent import BaseAgent
from app.models.generated_visuals import GeneratedVisuals
from app.models.presentation_plan import PresentationPlan
from app.models.reveal_result import RevealRenderResult
from app.models.speaker_notes import SpeakerNotes
from app.renderers.reveal_renderer import RevealRenderer


class RevealBuilderAgent(BaseAgent[RevealRenderResult]):
    """A9 concrete agent that can validate render plans and build Reveal output."""

    prompt_file = "A9_reveal_builder.txt"
    output_model = RevealRenderResult

    def render(
        self,
        *,
        presentation_plan: PresentationPlan,
        speaker_notes: SpeakerNotes,
        generated_visuals: GeneratedVisuals,
        output_dir: Path,
        asset_map: dict[str, str] | None = None,
    ) -> RevealRenderResult:
        """Deterministically render Reveal output files from structured inputs."""
        renderer = RevealRenderer()
        return renderer.render(
            presentation_plan=presentation_plan,
            speaker_notes=speaker_notes,
            generated_visuals=generated_visuals,
            asset_map=asset_map or {},
            output_dir=output_dir,
        )

    def plan_and_render(
        self,
        *,
        render_payload: dict[str, Any],
        presentation_plan: PresentationPlan,
        speaker_notes: SpeakerNotes,
        generated_visuals: GeneratedVisuals,
        output_dir: Path,
        asset_map: dict[str, str] | None = None,
    ) -> RevealRenderResult:
        """Optionally run LLM planning before deterministic file rendering."""
        _ = self.run(render_payload)
        return self.render(
            presentation_plan=presentation_plan,
            speaker_notes=speaker_notes,
            generated_visuals=generated_visuals,
            output_dir=output_dir,
            asset_map=asset_map,
        )
