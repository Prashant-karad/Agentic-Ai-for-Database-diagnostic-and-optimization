"""Where the simulated shop's database is. Read from the environment / .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

# settings.py is at <root>/src/shopsim/settings.py -> go up 2 folders to <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ShopSettingsError(Exception):
    """Raised when the shop's database URL is not configured."""


def load_shop_db_url(env_file: Path = PROJECT_ROOT / ".env") -> str:
    """Connection URL of the shop's database (the database the agent watches)."""
    load_dotenv(env_file)
    url = os.getenv("SHOP_DB_URL")
    if not url:
        raise ShopSettingsError("Missing setting 'SHOP_DB_URL'. Add it to .env (see .env.example).")
    return url