"""Application settings, loaded from environment variables (.env file)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# config.py is at <root>/src/dbagent/core/config.py -> go up 3 folders to <root>
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ConfigError(Exception):
    """Raised when a required setting is missing."""


@dataclass(frozen=True)
class Settings:
    main_db_url: str


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    api_key: str
    model: str


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(
            f"Missing required setting '{name}'. "
            "Did you copy .env.example to .env and fill it in?"
        )
    return value


def load_settings(env_file: Path = PROJECT_ROOT / ".env") -> Settings:
    """Read settings. Real environment variables win over values in env_file."""
    load_dotenv(env_file)
    return Settings(main_db_url=_require("MAIN_DB_URL"))


def load_llm_settings(env_file: Path = PROJECT_ROOT / ".env") -> LLMSettings:
    """Read the LLM settings. Kept separate so database-only scripts work without an API key."""
    load_dotenv(env_file)
    return LLMSettings(
        base_url=_require("LLM_BASE_URL"),
        api_key=_require("LLM_API_KEY"),
        model=_require("LLM_MODEL"),
    )