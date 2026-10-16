"""Quick check that Python can reach the main database."""

from dbagent.core.config import load_settings
from dbagent.core.db import Database


def main() -> None:
    settings = load_settings()
    db = Database(settings.main_db_url, name="main")

    info = db.fetch_one("SELECT version() AS version, current_user AS db_user")
    print("Connected as:", info["db_user"])
    print("Server:", info["version"])

    counts = db.fetch_one(
        """
        SELECT (SELECT count(*) FROM customers) AS customers,
               (SELECT count(*) FROM products)  AS products,
               (SELECT count(*) FROM orders)    AS orders
        """
    )
    print("Row counts:", counts)

    customer_id = 4242
    rows = db.fetch_all(
        "SELECT id, status, total FROM orders WHERE customer_id = %s "
        "ORDER BY created_at DESC LIMIT 3",
        (customer_id,),
    )
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()