"""Tests for shopsim.settings."""

import pytest

from shopsim.settings import ShopSettingsError, load_shop_db_url


def test_reads_shop_db_url(tmp_path, monkeypatch):
    monkeypatch.delenv("SHOP_DB_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SHOP_DB_URL=postgresql://u:p@localhost:5432/shop\n")

    assert load_shop_db_url(env_file) == "postgresql://u:p@localhost:5432/shop"


def test_missing_shop_db_url_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SHOP_DB_URL", raising=False)

    with pytest.raises(ShopSettingsError, match="SHOP_DB_URL"):
        load_shop_db_url(tmp_path / "missing.env")