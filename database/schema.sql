CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    phone         TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS addresses (
    address_id    TEXT PRIMARY KEY,
    customer_id   TEXT REFERENCES customers(customer_id),
    line1         TEXT NOT NULL,
    line2         TEXT,
    city          TEXT NOT NULL,
    state         TEXT NOT NULL,
    zip           TEXT NOT NULL,
    country       TEXT DEFAULT 'US',
    is_default    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT PRIMARY KEY,
    customer_id      TEXT REFERENCES customers(customer_id),
    status           TEXT NOT NULL,  -- pending, shipped, delivered, cancelled, returned
    shipping_address TEXT,           -- address_id (NULL if not yet assigned)
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id     TEXT PRIMARY KEY,
    order_id    TEXT REFERENCES orders(order_id),
    product     TEXT NOT NULL,
    quantity    INTEGER DEFAULT 1,
    unit_price  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id  TEXT PRIMARY KEY,
    order_id    TEXT REFERENCES orders(order_id),
    amount      REAL NOT NULL,
    status      TEXT DEFAULT 'completed',  -- completed, failed, refunded
    paid_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id   TEXT PRIMARY KEY,
    order_id    TEXT REFERENCES orders(order_id),
    amount      REAL NOT NULL,
    reason      TEXT,
    status      TEXT DEFAULT 'pending',   -- pending, completed, rejected
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS policies (
    policy_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,   -- refund, shipping, cancellation, returns
    content     TEXT NOT NULL
);
