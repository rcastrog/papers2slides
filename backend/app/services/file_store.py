"""Filesystem helpers for writing agent and run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class FileStore:
	"""Simple filesystem-backed store for text and JSON artifacts."""

	def write_text(self, path: Path, value: str) -> None:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(value, encoding="utf-8")

	def write_json(self, path: Path, value: Mapping[str, Any]) -> None:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
