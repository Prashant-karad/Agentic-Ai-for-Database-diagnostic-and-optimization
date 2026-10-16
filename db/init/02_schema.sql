-- E-commerce schema for the Query Optimizer Agent.
-- NOTE: orders.customer_id deliberately has NO index.
-- This is the planted problem the agent should discover and fix.

CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    email       TEXT        NOT NULL,
    city        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id        SERIAL PRIMARY KEY,
    name      TEXT          NOT NULL,
    category  TEXT          NOT NULL,
    price     NUMERIC(10,2) NOT NULL
);

CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INT           NOT NULL REFERENCES customers(id),
    product_id   INT           NOT NULL REFERENCES products(id),
    status       TEXT          NOT NULL,
    total        NUMERIC(10,2) NOT NULL,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now()
);