"""Thin wrapper around psycopg, so the rest of the project never handles raw connections."""

import psycopg
from psycopg.rows import dict_row


class Database:
    """One PostgreSQL database (main or sandbox) the agents can query."""

    def __init__(self, url: str, name: str = "db", statement_timeout_ms: int = 30_000):
        self.url = url
        self.name = name
        self.statement_timeout_ms = statement_timeout_ms

    def _connect(self, autocommit: bool = False) -> psycopg.Connection:
        return psycopg.connect(
            self.url,
            row_factory=dict_row,
            connect_timeout=5,
            options=f"-c statement_timeout={self.statement_timeout_ms}",
            autocommit=autocommit,
        )

    def fetch_all(self, sql: str, params: tuple | dict | None = None) -> list[dict]:
        """Run a query and return all rows as a list of dicts."""
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params: tuple | dict | None = None) -> dict | None:
        """Run a query and return the first row (or None)."""
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | dict | None = None) -> None:
        """Run a statement that changes something (CREATE INDEX, INSERT ...)."""
        with self._connect() as conn:
            conn.execute(sql, params)

    def execute_autocommit(self, sql: str, params: tuple | dict | None = None) -> None:
        """Run one statement outside a transaction (CREATE INDEX CONCURRENTLY needs this)."""
        with self._connect(autocommit=True) as conn:
            conn.execute(sql, params)