"""Things you can do to the shop to create (or remove) problems for the agent."""

from shopsim.database import ShopDatabase
from shopsim.traffic import TrafficGenerator

HEALTHY_INDEX = "CREATE INDEX IF NOT EXISTS idx_orders_customer_created ON orders (customer_id, created_at DESC)"

EXTRA_INDEXES_SQL = """
SELECT indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('orders', 'products', 'customers')
  AND indexname NOT LIKE '%pkey'
ORDER BY indexname
"""


def list_extra_indexes(db: ShopDatabase) -> list[str]:
    """All indexes on the shop tables except the primary keys."""
    return db.fetch_column(EXTRA_INDEXES_SQL)


def make_healthy(db: ShopDatabase) -> str:
    """Create the index that keeps 'my orders' fast."""
    db.execute(HEALTHY_INDEX)
    return "Created the index for 'my orders'. The shop is healthy."


def drop_indexes(db: ShopDatabase) -> str:
    """Remove every non-primary-key index: the classic 'someone dropped an index' mistake."""
    dropped = list_extra_indexes(db)
    for name in dropped:
        db.execute(f"DROP INDEX IF EXISTS {name}")  # names come from pg_indexes, not from users
    if not dropped:
        return "There were no extra indexes to drop."
    return f"Dropped {len(dropped)} index(es): {', '.join(dropped)}"


def start_flash_sale(traffic: TrafficGenerator, users: int = 20) -> str:
    """Many more users, mostly browsing categories."""
    traffic.set_mode("flash_sale")
    traffic.start(users)
    return f"Flash sale started: {users} users, mostly browsing categories."


def end_flash_sale(traffic: TrafficGenerator, users: int = 4) -> str:
    traffic.set_mode("normal")
    if traffic.is_running:
        traffic.set_users(users)
    return f"Flash sale ended: back to {users} users, normal traffic."


def reset(db: ShopDatabase, traffic: TrafficGenerator, users: int = 4) -> str:
    """Back to the starting point: normal traffic, only the healthy index."""
    end_flash_sale(traffic, users)
    drop_indexes(db)
    make_healthy(db)
    traffic.stats.reset()
    return "Reset: normal traffic, healthy index only, statistics cleared."