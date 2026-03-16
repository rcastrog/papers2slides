"""Prompt loader for composing master and agent prompts."""

from __future__ import annotations

from pathlib import Path


class PromptLoader:
    """Load and combine master prompt with an agent prompt file."""

    def __init__(
        self,
        prompts_dir: Path | None = None,
        master_prompt_filename: str = "master_global_prompt.txt",
    ) -> None:
        self._prompts_dir = prompts_dir or (Path(__file__).resolve().parents[1] / "prompts")
        self._master_prompt_filename = master_prompt_filename

    def load_agent_prompt(self, agent_prompt_filename: str) -> str:
        """Load master prompt and agent prompt and return one system prompt string."""
        master_prompt = self._read_required_prompt(self._master_prompt_filename)
        agent_prompt = self._read_required_prompt(agent_prompt_filename)
        return f"{master_prompt}\n\n{agent_prompt}".strip()

    def _read_required_prompt(self, prompt_filename: str) -> str:
        prompt_path = self._prompts_dir / prompt_filename
        if not prompt_path.is_file():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8").strip()
