"""Tests for LLM payload serialization helpers."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.llm_client import FallbackOnAuthErrorTransport, LLMClient, _dumps_payload


class _SampleModel(BaseModel):
    value: str


class LLMClientSerializationTest(unittest.TestCase):
    def test_dumps_payload_serializes_pydantic_and_path_objects(self) -> None:
        payload = {
            "entry": _SampleModel(value="ok"),
            "path": Path("a/b/c.txt"),
            "items": {"x", "y"},
        }

        dumped = _dumps_payload(payload)
        parsed = json.loads(dumped)

        self.assertEqual(parsed["entry"]["value"], "ok")
        self.assertTrue(parsed["path"].endswith("a\\b\\c.txt") or parsed["path"].endswith("a/b/c.txt"))
        self.assertEqual(sorted(parsed["items"]), ["x", "y"])


class _StaticTransport:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    def complete(self, system_prompt: str, input_payload: dict[str, object], model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        self.calls += 1
        return self._response


class _RaisingTransport:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    def complete(self, system_prompt: str, input_payload: dict[str, object], model: str | None = None) -> str:
        _ = (system_prompt, input_payload, model)
        self.calls += 1
        raise self._error


class AuthFallbackTransportTest(unittest.TestCase):
    def test_primary_success_does_not_activate_fallback(self) -> None:
        primary = _StaticTransport('{"ok": true}')
        fallback = _StaticTransport('{"fallback": true}')
        wrapped = FallbackOnAuthErrorTransport(primary=primary, fallback=fallback)

        client = LLMClient(transport=wrapped)
        result = client.generate("system", {"k": "v"})

        self.assertEqual(json.loads(result)["ok"], True)
        self.assertFalse(client.used_auth_fallback())
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)

    def test_auth_error_activates_fallback_for_subsequent_calls(self) -> None:
        primary = _RaisingTransport(RuntimeError("DefaultAzureCredential failed to retrieve a token"))
        fallback = _StaticTransport('{"ok": true}')
        wrapped = FallbackOnAuthErrorTransport(primary=primary, fallback=fallback)

        client = LLMClient(transport=wrapped)
        first = client.generate("system", {"k": "v"})
        second = client.generate("system", {"k": "v2"})

        self.assertEqual(json.loads(first)["ok"], True)
        self.assertEqual(json.loads(second)["ok"], True)
        self.assertTrue(client.used_auth_fallback())
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 2)

    def test_non_auth_errors_are_not_swallowed(self) -> None:
        primary = _RaisingTransport(RuntimeError("network timeout"))
        fallback = _StaticTransport('{"ok": true}')
        wrapped = FallbackOnAuthErrorTransport(primary=primary, fallback=fallback)

        with self.assertRaises(RuntimeError):
            wrapped.complete("system", {"k": "v"})

        self.assertFalse(wrapped.fallback_activated)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)


if __name__ == "__main__":
    unittest.main()
