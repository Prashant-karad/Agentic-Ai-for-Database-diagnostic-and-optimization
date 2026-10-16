"""Tests for dbagent.core.config."""

import pytest

from dbagent.core.config import ConfigError, load_settings


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