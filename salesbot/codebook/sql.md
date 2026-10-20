# SQL (PostgreSQL, SQLite, MySQL)
## Rules
- Always parameterized queries (`?`, `$1`, `%s` depending on driver). Never concatenate user input.
- Every table: primary key, `created_at` timestamp, NOT NULL where possible, foreign keys with ON DELETE rule.
- Index columns used in WHERE/JOIN/ORDER BY. Use transactions for multi-step writes.
## Templates
```sql
CREATE TABLE customers (
  id BIGSERIAL PRIMARY KEY,               -- SQLite: INTEGER PRIMARY KEY AUTOINCREMENT
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY,
  customer_id BIGINT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX orders_customer ON orders (customer_id, created_at DESC);

-- top customers by spend in the last 30 days
SELECT c.name, SUM(o.total_cents) / 100.0 AS spent
FROM orders o JOIN customers c ON c.id = o.customer_id
WHERE o.created_at >= now() - INTERVAL '30 days'
GROUP BY c.id, c.name
ORDER BY spent DESC
LIMIT 10;

-- upsert
INSERT INTO customers (email, name) VALUES ($1, $2)
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;
```
Window functions: `ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC)`.
Supabase/Postgres row-level security: `ALTER TABLE t ENABLE ROW LEVEL SECURITY; CREATE POLICY own ON t USING (auth.uid() = user_id);`
## Pitfalls
- `NULL = NULL` is not true: use `IS NULL`. `COUNT(col)` skips NULLs; `COUNT(*)` doesn't.
- Every non-aggregated SELECT column must be in GROUP BY. `LIKE '%x%'` can't use a normal index.
- Money as integer cents or NUMERIC, never FLOAT.
