"""Agent for parsing source papers into structured parse output."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.agents.base_agent import BaseAgent
from app.models.parse_result import PaperParseResult


class ParserAgent(BaseAgent[PaperParseResult]):
    """A1 concrete agent with optional deterministic parse context inputs."""

    prompt_file = "A1_paper_parser.txt"
    output_model = PaperParseResult

    def run(
        self,
        input_payload: dict[str, Any] | None = None,
        *,
        pdf_path: str | Path | None = None,
        extracted_text_payload: dict[str, Any] | None = None,
        section_candidates: list[Any] | None = None,
    ) -> PaperParseResult:
        """Run A1 with optional deterministic extraction artifacts included in the payload."""
        payload: dict[str, Any] = dict(input_payload or {})

        if pdf_path is not None:
            payload["pdf_path"] = str(pdf_path)
        if extracted_text_payload is not None:
            payload["extracted_text"] = extracted_text_payload
        if section_candidates is not None:
            payload["section_candidates"] = [self._to_dict(item) for item in section_candidates]

        return super().run(payload)

    @staticmethod
    def _to_dict(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        if is_dataclass(item):
            return asdict(item)
        raise TypeError("section_candidates entries must be dicts or dataclass instances")
