"""The shop's own small database helper (separate from the agent's)."""

import psycopg


class ShopDatabase:
    """Runs admin statements on the shop database (used by the fault scenarios)."""

    def __init__(self, url: str):
        self.url = url

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True, connect_timeout=5, application_name="shop-admin")

    def execute(self, sql: str) -> None:
        with self._connect() as conn:
            conn.execute(sql)

    def fetch_column(self, sql: str) -> list:
        """Run a query and return the first column of every row."""
        with self._connect() as conn:
            return [row[0] for row in conn.execute(sql).fetchall()]