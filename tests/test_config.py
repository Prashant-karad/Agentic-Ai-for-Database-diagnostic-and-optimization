"""Tests for dbagent.core.config."""

import pytest

from dbagent.core.config import ConfigError, load_llm_settings, load_sandbox_db_url, load_settings

def test_reads_url_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIN_DB_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("MAIN_DB_URL=postgresql://u:p@localhost:5432/shop\n")

    settings = load_settings(env_file)

    assert settings.main_db_url == "postgresql://u:p@localhost:5432/shop"


def test_missing_url_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("MAIN_DB_URL", raising=False)

    with pytest.raises(ConfigError, match="MAIN_DB_URL"):
        load_settings(tmp_path / "does_not_exist.env")


def test_reads_llm_settings(tmp_path, monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_BASE_URL=https://x/v1\nLLM_API_KEY=abc\nLLM_MODEL=m1\n")

    settings = load_llm_settings(env_file)

    assert (settings.base_url, settings.api_key, settings.model) == ("https://x/v1", "abc", "m1")


def test_missing_llm_key_raises_clear_error(tmp_path, monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_BASE_URL=https://x/v1\nLLM_MODEL=m1\n")

    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        load_llm_settings(env_file)




def test_reads_sandbox_url(tmp_path, monkeypatch):
    monkeypatch.delenv("SANDBOX_DB_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SANDBOX_DB_URL=postgresql://u:p@localhost:5433/shop\n")

    assert load_sandbox_db_url(env_file) == "postgresql://u:p@localhost:5433/shop"