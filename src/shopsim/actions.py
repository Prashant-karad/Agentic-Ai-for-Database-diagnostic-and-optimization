"""What the simulated shop customers do: each action is one SQL query with random values.

Two traffic modes:
  normal      - a typical day (lots of "my orders" and product pages)
  flash_sale  - a big sale (most people are browsing categories)
"""

import random
from collections.abc import Callable
from dataclasses import dataclass

CATEGORIES = ("electronics", "books", "fashion", "home", "sports")
CUSTOMER_COUNT = 200_000
PRODUCT_COUNT = 10_000
MODES = ("normal", "flash_sale")


@dataclass(frozen=True)
class ShopAction:
    """One thing a customer can do on the shop."""

    name: str
    sql: str
    make_params: Callable[[random.Random], tuple]
    weights: dict[str, int]          # how often it happens in each mode (relative)


ACTIONS = (
    ShopAction(
        name="my_orders",
        sql="SELECT id, status, total, created_at FROM orders "
            "WHERE customer_id = %s ORDER BY created_at DESC LIMIT 10",
        make_params=lambda rng: (rng.randint(1, CUSTOMER_COUNT),),
        weights={"normal": 40, "flash_sale": 15},
    ),
    ShopAction(
        name="product_page",
        sql="SELECT id, name, category, price FROM products WHERE id = %s",
        make_params=lambda rng: (rng.randint(1, PRODUCT_COUNT),),
        weights={"normal": 30, "flash_sale": 25},
    ),
    ShopAction(
        name="browse_category",
        sql="SELECT id, name, price FROM products WHERE category = %s ORDER BY price LIMIT 20",
        make_params=lambda rng: (rng.choice(CATEGORIES),),
        weights={"normal": 15, "flash_sale": 45},
    ),
    ShopAction(
        name="customer_profile",
        sql="SELECT name, email, city FROM customers WHERE id = %s",
        make_params=lambda rng: (rng.randint(1, CUSTOMER_COUNT),),
        weights={"normal": 10, "flash_sale": 5},
    ),
    ShopAction(
        name="place_order",
        sql="INSERT INTO orders (customer_id, product_id, status, total) VALUES (%s, %s, 'placed', %s)",
        make_params=lambda rng: (
            rng.randint(1, CUSTOMER_COUNT),
            rng.randint(1, PRODUCT_COUNT),
            round(rng.uniform(10, 5000), 2),
        ),
        weights={"normal": 5, "flash_sale": 10},
    ),
)


def choose_action(rng: random.Random, mode: str = "normal") -> ShopAction:
    """Pick the next action at random, following the weights of the given mode."""
    if mode not in MODES:
        raise ValueError(f"Unknown traffic mode {mode!r}; expected one of {MODES}.")
    weights = [action.weights[mode] for action in ACTIONS]
    return rng.choices(ACTIONS, weights=weights, k=1)[0]