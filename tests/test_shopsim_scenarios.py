"""Tests for the shop's fault scenarios (mock database, no real changes)."""

from shopsim.scenarios import drop_indexes, make_healthy


class MockShopDatabase:
    """Stands in for ShopDatabase: remembers indexes and executed SQL."""

    def __init__(self, indexes):
        self.indexes = list(indexes)
        self.executed: list[str] = []

    def fetch_column(self, sql):
        return list(self.indexes)

    def execute(self, sql):
        self.executed.append(sql)
        if sql.startswith("DROP INDEX"):
            self.indexes.remove(sql.split()[-1])


def test_drop_indexes_removes_every_listed_index():
    db = MockShopDatabase(["idx_a", "idx_b"])

    message = drop_indexes(db)

    assert db.indexes == []
    assert "Dropped 2" in message


def test_drop_indexes_with_nothing_to_drop():
    assert "no extra indexes" in drop_indexes(MockShopDatabase([]))


def test_make_healthy_creates_the_orders_index():
    db = MockShopDatabase([])

    make_healthy(db)

    assert "idx_orders_customer_created" in db.executed[0]