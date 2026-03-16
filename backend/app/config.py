"""Runtime configuration helpers for LLM provider selection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LLMSettings:
    """Environment-backed settings used to build the workflow LLM client."""

    llm_provider: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    use_mock_llm: bool = False
    openai_api_key: str = ""
    openai_base_url: str | None = None
    openai_timeout_seconds: float = 60.0
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-02-15-preview"
    azure_openai_deployment: str = ""
    azure_openai_use_entra: bool = True
    image_gen_enabled: bool = False
    image_gen_model: str = "dall-e-3"
    image_gen_size: str = "1792x1024"
    image_gen_quality: str = "hd"
    image_gen_max_images_per_run: int = 4
    image_gen_max_retries_per_image: int = 2
    image_gen_retry_delay_seconds: float = 1.0

    @property
    def provider(self) -> str:
        return (self.llm_provider or "").strip().lower()

    @property
    def has_openai_config(self) -> bool:
        return self.provider == "openai" and bool(self.openai_api_key.strip())

    @property
    def has_azure_openai_config(self) -> bool:
        if self.provider != "azure_openai":
            return False
        has_auth = bool((self.azure_openai_api_key or "").strip()) or self.azure_openai_use_entra
        return bool((self.azure_openai_endpoint or "").strip()) and bool((self.azure_openai_deployment or "").strip()) and has_auth

    @classmethod
    def from_env(cls) -> "LLMSettings":
        _load_backend_dotenv()
        azure_deployment = (os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip() or os.getenv("LLM_MODEL", "").strip())
        return cls(
            llm_provider=os.getenv("LLM_PROVIDER", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            llm_temperature=_read_float("LLM_TEMPERATURE", 0.0),
            use_mock_llm=_read_bool("USE_MOCK_LLM", False),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_base_url=_read_optional("OPENAI_API_BASE"),
            openai_timeout_seconds=_read_float("OPENAI_TIMEOUT_SECONDS", 60.0),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", "").strip(),
            azure_openai_endpoint=_read_optional("AZURE_OPENAI_ENDPOINT"),
            azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview").strip() or "2024-02-15-preview",
            azure_openai_deployment=azure_deployment,
            azure_openai_use_entra=_read_bool("AZURE_OPENAI_USE_ENTRA", True),
            image_gen_enabled=_read_bool("ENABLE_OPENAI_IMAGE_GEN", False) and not bool(os.getenv("PYTEST_CURRENT_TEST")),
            image_gen_model=os.getenv("OPENAI_IMAGE_MODEL", "dall-e-3").strip() or "dall-e-3",
            image_gen_size=os.getenv("OPENAI_IMAGE_SIZE", "1792x1024").strip() or "1792x1024",
            image_gen_quality=os.getenv("OPENAI_IMAGE_QUALITY", "hd").strip() or "hd",
            image_gen_max_images_per_run=_read_int("OPENAI_IMAGE_MAX_IMAGES_PER_RUN", 4),
            image_gen_max_retries_per_image=_read_int("OPENAI_IMAGE_MAX_RETRIES", 2),
            image_gen_retry_delay_seconds=_read_float("OPENAI_IMAGE_RETRY_DELAY_SECONDS", 1.0),
        )


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _read_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _read_optional(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _load_backend_dotenv() -> None:
    """Load backend/.env into process environment when variables are not already exported."""
    dotenv_path = (os.getenv("PAPER2SLIDES_ENV_FILE") or str(Path(__file__).resolve().parents[1] / ".env")).strip()
    if not dotenv_path:
        return

    path = Path(dotenv_path)
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        normalized = value.strip().strip('"').strip("'")
        os.environ[key] = normalized
