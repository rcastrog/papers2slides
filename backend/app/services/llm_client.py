"""Minimal, domain-agnostic LLM client wrapper."""

from __future__ import annotations

import json
import importlib
import re
from pathlib import Path
from typing import Any, Protocol


class LLMTransport(Protocol):
    """Low-level transport that executes model requests."""

    def complete(self, system_prompt: str, input_payload: dict[str, Any], model: str | None = None) -> str:
        """Return raw text from the underlying model API."""


class SequentialMockTransport:
    """Deterministic transport that returns pre-seeded JSON payloads in order."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self._index = 0

    def complete(self, system_prompt: str, input_payload: dict[str, Any], model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        if self._index >= len(self._responses):
            raise RuntimeError("No mock response available for this LLM call")

        payload = self._responses[self._index]
        self._index += 1
        return json.dumps(payload)


class FallbackOnAuthErrorTransport:
    """Transport wrapper that falls back when runtime auth is unavailable."""

    def __init__(self, *, primary: LLMTransport, fallback: LLMTransport) -> None:
        self._primary = primary
        self._fallback = fallback
        self.fallback_activated = False

    def complete(self, system_prompt: str, input_payload: dict[str, Any], model: str | None = None) -> str:
        if self.fallback_activated:
            return self._fallback.complete(system_prompt, input_payload, model)

        try:
            return self._primary.complete(system_prompt, input_payload, model)
        except Exception as exc:
            if not _looks_like_auth_failure(exc):
                raise
            self.fallback_activated = True
            return self._fallback.complete(system_prompt, input_payload, model)


class OpenAIChatTransport:
    """OpenAI Chat Completions transport with JSON-object response discipline."""

    def __init__(
        self,
        *,
        api_key: str,
        default_model: str,
        base_url: str | None = None,
        temperature: float = 0.0,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required for OpenAI transport")
        if not default_model.strip():
            raise ValueError("LLM_MODEL is required for OpenAI transport")

        try:
            openai_module = importlib.import_module("openai")
            openai_cls = getattr(openai_module, "OpenAI")
        except Exception as exc:
            raise RuntimeError("openai package is required for real LLM mode. Install it with 'pip install openai'.") from exc

        self._client = openai_cls(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self._default_model = default_model
        self._temperature = temperature

    def complete(self, system_prompt: str, input_payload: dict[str, Any], model: str | None = None) -> str:
        resolved_model = (model or self._default_model).strip()
        if not resolved_model:
            raise ValueError("No model was provided for OpenAI request")

        response = self._client.chat.completions.create(
            model=resolved_model,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        "Return only one JSON object with no Markdown fences and no extra text."
                    ),
                },
                {
                    "role": "user",
                    "content": _dumps_payload(input_payload),
                },
            ],
        )

        content = response.choices[0].message.content if response.choices else ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_chunks = [getattr(chunk, "text", "") for chunk in content]
            return "".join(item for item in text_chunks if item)
        return str(content)


class AzureOpenAIChatTransport:
    """Azure OpenAI Chat Completions transport with JSON-object response discipline."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        api_version: str,
        deployment: str,
        use_entra: bool = True,
        temperature: float = 0.0,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not endpoint.strip():
            raise ValueError("AZURE_OPENAI_ENDPOINT is required for Azure OpenAI transport")
        if not deployment.strip():
            raise ValueError("AZURE_OPENAI_DEPLOYMENT is required for Azure OpenAI transport")

        try:
            openai_module = importlib.import_module("openai")
            azure_openai_cls = getattr(openai_module, "AzureOpenAI")
        except Exception as exc:
            raise RuntimeError("openai package is required for Azure OpenAI mode. Install it with 'pip install openai'.") from exc

        auth_kwargs: dict[str, Any]
        if api_key.strip():
            auth_kwargs = {"api_key": api_key}
        elif use_entra:
            try:
                identity_module = importlib.import_module("azure.identity")
                default_credential_cls = getattr(identity_module, "DefaultAzureCredential")
                token_provider_factory = getattr(identity_module, "get_bearer_token_provider")
            except Exception as exc:
                raise RuntimeError(
                    "azure-identity is required for Azure OpenAI Entra auth. Install it with 'pip install azure-identity'."
                ) from exc

            credential = default_credential_cls()
            token_provider = token_provider_factory(credential, "https://cognitiveservices.azure.com/.default")
            auth_kwargs = {"azure_ad_token_provider": token_provider}
        else:
            raise ValueError("AZURE_OPENAI_API_KEY is required when AZURE_OPENAI_USE_ENTRA=false")

        self._client = azure_openai_cls(
            azure_endpoint=endpoint,
            api_version=api_version,
            timeout=timeout_seconds,
            **auth_kwargs,
        )
        self._deployment = deployment
        self._temperature = temperature

    def complete(self, system_prompt: str, input_payload: dict[str, Any], model: str | None = None) -> str:
        deployment = (model or self._deployment).strip()
        if not deployment:
            raise ValueError("No Azure OpenAI deployment was provided")

        response = self._client.chat.completions.create(
            model=deployment,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\n"
                        "Return only one JSON object with no Markdown fences and no extra text."
                    ),
                },
                {
                    "role": "user",
                    "content": _dumps_payload(input_payload),
                },
            ],
        )

        content = response.choices[0].message.content if response.choices else ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_chunks = [getattr(chunk, "text", "") for chunk in content]
            return "".join(item for item in text_chunks if item)
        return str(content)


class LLMClient:
    """Tiny wrapper exposing a clean generate interface for agents."""

    def __init__(
        self,
        transport: LLMTransport,
        default_model: str | None = None,
    ) -> None:
        self._transport = transport
        self._default_model = default_model

    def generate(
        self,
        system_prompt: str,
        input_payload: dict[str, Any],
        model: str | None = None,
    ) -> str:
        """Send prompt + input payload and normalize output to JSON-object text."""
        resolved_model = model or self._default_model
        raw_text = self._transport.complete(system_prompt, input_payload, resolved_model)

        normalized = _normalize_json_object_text(raw_text)
        if normalized is not None:
            return normalized

        # One lightweight repair pass that asks the model to restate malformed output as strict JSON.
        repair_prompt = (
            "You must return exactly one valid JSON object and nothing else. "
            "Do not include Markdown fences, comments, or explanatory text."
        )
        repair_payload = {
            "original_system_prompt": system_prompt,
            "original_input_payload": input_payload,
            "malformed_response": raw_text,
        }
        repaired_text = self._transport.complete(repair_prompt, repair_payload, resolved_model)
        normalized_repair = _normalize_json_object_text(repaired_text)
        if normalized_repair is not None:
            return normalized_repair

        raise ValueError(
            "LLM response is not valid JSON after one repair attempt. "
            f"Initial sample: {_truncate(raw_text)} | Repair sample: {_truncate(repaired_text)}"
        )

    def used_auth_fallback(self) -> bool:
        return bool(getattr(self._transport, "fallback_activated", False))


def _normalize_json_object_text(raw_text: str) -> str | None:
    """Strip fences/noise and return canonical JSON object text if parsing succeeds."""
    candidate = (raw_text or "").strip()
    if not candidate:
        return None

    candidate = _strip_markdown_fence(candidate)
    if not candidate:
        return None

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None

    sliced = candidate[start : end + 1]
    try:
        parsed = json.loads(sliced)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return json.dumps(parsed, ensure_ascii=False)


def _json_default(value: Any) -> Any:
    """Serialize common workflow payload object types to JSON-friendly values."""
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return list(value)
    return str(value)


def _dumps_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=_json_default)


def _strip_markdown_fence(value: str) -> str:
    fenced_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        return fenced_match.group(1).strip()
    return value


def _truncate(value: str, limit: int = 240) -> str:
    text = (value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _looks_like_auth_failure(exc: Exception) -> bool:
    text = str(exc)
    if not text:
        return False
    lowered = text.lower()
    markers = [
        "defaultazurecredential failed",
        "clientauthenticationerror",
        "failed to retrieve a token",
        "authentication unavailable",
    ]
    return any(marker in lowered for marker in markers)
