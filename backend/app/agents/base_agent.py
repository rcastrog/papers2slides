"""Reusable base class for prompt-driven typed agents."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel

from app.services.llm_client import LLMClient
from app.services.prompt_loader import PromptLoader

if TYPE_CHECKING:
    from app.storage.run_manager import RunManager


TOutputModel = TypeVar("TOutputModel", bound=BaseModel)


class BaseAgent(Generic[TOutputModel]):
    """Shared flow: prompt load -> LLM call -> JSON parse -> model validation."""

    prompt_file: str
    output_model: type[TOutputModel]
    model: str | None = None

    def __init__(
        self,
        llm_client: LLMClient,
        prompt_loader: PromptLoader,
        run_manager: RunManager | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._prompt_loader = prompt_loader
        self._run_manager = run_manager

        if not getattr(self, "prompt_file", None):
            raise ValueError("BaseAgent subclasses must define prompt_file")
        if not getattr(self, "output_model", None):
            raise ValueError("BaseAgent subclasses must define output_model")

    def run(self, input_payload: dict[str, Any]) -> TOutputModel:
        """Run this agent and return validated typed output."""
        system_prompt = self._prompt_loader.load_agent_prompt(self.prompt_file)
        raw_text = self._llm_client.generate(system_prompt, input_payload, model=self.model)
        self._persist_raw_output(raw_text)
        parsed_payload = self._parse_json(raw_text)
        self._persist_validated_output(parsed_payload)
        return self.output_model.model_validate(parsed_payload)

    def _persist_raw_output(self, raw_text: str) -> None:
        if self._run_manager is None:
            return
        self._run_manager.save_text(
            relative_path=f"analysis/{self.__class__.__name__}_raw.txt",
            content=raw_text,
        )

    def _persist_validated_output(self, parsed_payload: dict[str, Any]) -> None:
        if self._run_manager is None:
            return
        self._run_manager.save_json(
            relative_path=f"analysis/{self.__class__.__name__}_validated.json",
            data=parsed_payload,
        )

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM output is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("LLM output must be a JSON object")
        return payload
