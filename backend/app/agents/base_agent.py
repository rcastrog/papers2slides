"""Reusable base class for prompt-driven typed agents."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

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

        first_error: Exception | None = None
        try:
            parsed_payload = self._parse_json(raw_text)
            self._persist_validated_output(parsed_payload)
            return self.output_model.model_validate(parsed_payload)
        except (ValueError, ValidationError) as exc:
            first_error = exc

        repair_prompt = self._build_repair_prompt(system_prompt=system_prompt, first_error=first_error)
        repair_payload = {
            "original_input": input_payload,
            "previous_output_text": raw_text,
            "validation_error": str(first_error),
            "required_schema": self.output_model.model_json_schema(),
        }
        repaired_text = self._llm_client.generate(repair_prompt, repair_payload, model=self.model)
        self._persist_raw_output(repaired_text, suffix="retry1")
        parsed_payload = self._parse_json(repaired_text)
        self._persist_validated_output(parsed_payload, suffix="retry1")
        return self.output_model.model_validate(parsed_payload)

    def _persist_raw_output(self, raw_text: str, *, suffix: str | None = None) -> None:
        if self._run_manager is None:
            return
        filename_suffix = f"_{suffix}" if suffix else ""
        self._run_manager.save_text(
            relative_path=f"analysis/{self.__class__.__name__}_raw{filename_suffix}.txt",
            content=raw_text,
        )

    def _persist_validated_output(self, parsed_payload: dict[str, Any], *, suffix: str | None = None) -> None:
        if self._run_manager is None:
            return
        filename_suffix = f"_{suffix}" if suffix else ""
        self._run_manager.save_json(
            relative_path=f"analysis/{self.__class__.__name__}_validated{filename_suffix}.json",
            data=parsed_payload,
        )

    def _build_repair_prompt(self, *, system_prompt: str, first_error: Exception | None) -> str:
        return (
            f"{system_prompt}\n\n"
            "Your previous output did not validate against the required schema. "
            "Return ONLY a JSON object that matches the required schema exactly. "
            "Do not include markdown, explanations, or any extra keys. "
            f"Validation error from previous output: {first_error}"
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
