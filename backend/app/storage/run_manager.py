"""Simple run-folder manager for agent artifacts."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunManager:
    """Creates run folders and persists text/JSON artifacts."""

    _SUBDIRS = (
        "input",
        "source_paper",
        "analysis",
        "artifacts",
        "references",
        "presentation",
        "audit",
        "logs",
    )

    def __init__(self, runs_root: Path) -> None:
        self._runs_root = runs_root
        self._runs_root.mkdir(parents=True, exist_ok=True)
        self._run_path: Path | None = None

    def create_run(self, slug: str | None = None) -> Path:
        """Create and select a unique run folder under runs_root."""
        base_name = self._build_run_name(slug)
        run_path = self._runs_root / base_name
        suffix = 1
        while run_path.exists():
            run_path = self._runs_root / f"{base_name}_{suffix}"
            suffix += 1

        run_path.mkdir(parents=True, exist_ok=False)
        self._run_path = run_path
        self.ensure_subdirs()
        return run_path

    def get_run_path(self) -> Path:
        """Return the active run path after create_run has been called."""
        if self._run_path is None:
            raise RuntimeError("Run has not been created yet. Call create_run() first.")
        return self._run_path

    def set_run_path(self, run_path: Path) -> Path:
        """Set an existing run folder as active and ensure expected subdirs."""
        resolved = run_path.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        self._run_path = resolved
        self.ensure_subdirs()
        return resolved

    def get_run_path_by_id(self, run_id: str) -> Path:
        """Resolve a run folder path by run id and validate it exists."""
        if not run_id:
            raise ValueError("run_id cannot be empty")
        run_path = (self._runs_root / run_id).expanduser().resolve()
        if not run_path.is_dir():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return run_path

    def ensure_subdirs(self) -> None:
        """Ensure the standard run subdirectory structure exists."""
        run_path = self.get_run_path()
        for subdir in self._SUBDIRS:
            (run_path / subdir).mkdir(parents=True, exist_ok=True)

    def save_json(self, relative_path: str, data: dict[str, Any]) -> Path:
        """Save a JSON artifact under the current run folder."""
        target_path = self._resolve_run_target(relative_path)
        target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return target_path

    def save_text(self, relative_path: str, content: str) -> Path:
        """Save a text artifact under the current run folder."""
        target_path = self._resolve_run_target(relative_path)
        target_path.write_text(content, encoding="utf-8")
        return target_path

    def read_json(self, relative_path: str) -> dict[str, Any] | None:
        """Read a JSON artifact under the current run folder when present."""
        target_path = self._resolve_run_existing_target(relative_path)
        if target_path is None:
            return None
        try:
            loaded = json.loads(target_path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def read_text(self, relative_path: str) -> str | None:
        """Read a text artifact under the current run folder when present."""
        target_path = self._resolve_run_existing_target(relative_path)
        if target_path is None:
            return None
        try:
            return target_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _resolve_run_target(self, relative_path: str) -> Path:
        run_path = self.get_run_path()
        if not relative_path:
            raise ValueError("relative_path cannot be empty")

        relative_target = Path(relative_path)
        if relative_target.is_absolute():
            raise ValueError("relative_path must be relative to the run folder")

        target_path = run_path / relative_target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        return target_path

    def _resolve_run_existing_target(self, relative_path: str) -> Path | None:
        run_path = self.get_run_path()
        if not relative_path:
            raise ValueError("relative_path cannot be empty")

        relative_target = Path(relative_path)
        if relative_target.is_absolute():
            raise ValueError("relative_path must be relative to the run folder")

        target_path = (run_path / relative_target).resolve()
        if not target_path.is_file():
            return None
        return target_path

    @staticmethod
    def _build_run_name(slug: str | None) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        if slug is None:
            return f"run_{timestamp}"

        normalized_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-")
        if not normalized_slug:
            normalized_slug = "run"
        return f"{normalized_slug}_{timestamp}"
