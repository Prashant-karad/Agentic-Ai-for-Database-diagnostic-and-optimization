-- Generate realistic fake e-commerce data.
-- 200k customers, 10k products, 2M orders. Takes ~40-60 seconds.

-- Fixed seed so everyone gets identical data (reproducible results).
SELECT setseed(0.42);

INSERT INTO customers (name, email, city, created_at)
SELECT 'user' || g,
       'user' || g || '@mail.com',
       (ARRAY['Pune','Mumbai','Delhi','Nagpur','Nashik'])[1 + g % 5],
       now() - (g % 1000) * interval '1 day'
FROM generate_series(1, 200000) AS g;

INSERT INTO products (name, category, price)
SELECT 'product' || g,
       (ARRAY['electronics','books','fashion','home','sports'])[1 + g % 5],
       round((10 + random() * 990)::numeric, 2)
FROM generate_series(1, 10000) AS g;

INSERT INTO orders (customer_id, product_id, status, total, created_at)
SELECT 1 + floor(random() * 200000)::int,
       1 + floor(random() * 10000)::int,
       (ARRAY['placed','shipped','delivered','cancelled'])[1 + floor(random() * 4)::int],
       round((random() * 5000)::numeric, 2),
       now() - random() * interval '365 days'
FROM generate_series(1, 2000000);

-- Update the planner's statistics about the new data.
ANALYZE;