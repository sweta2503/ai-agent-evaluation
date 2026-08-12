"""Seed the SQLite database with realistic fake data."""
import sqlite3, uuid, random
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "ops.db"
SCHEMA  = Path(__file__).parent / "schema.sql"

FIRST_NAMES = [
    "Sarah","Michael","Priya","John","Amy","David","Lisa","James","Emma","Carlos",
    "Aisha","Tom","Nina","Kevin","Zoe","Marcus","Diana","Ryan","Mei","Omar",
    "Julia","Chris","Nadia","Andre","Sofia","Ben","Chloe","Eric","Layla","Sam",
]
LAST_NAMES = [
    "Smith","Johnson","Patel","Williams","Chen","Brown","Davis","Wilson","Taylor","Lee",
    "Kim","Martinez","Garcia","Anderson","Thomas","Harris","Martin","White","Moore","Hall",
]
PRODUCTS = [
    ("Wireless Headphones", 79.99),
    ("USB-C Hub",           34.99),
    ("Mechanical Keyboard", 129.99),
    ("Webcam 1080p",        59.99),
    ("Monitor Stand",       49.99),
    ("Laptop Sleeve",       24.99),
    ("Desk Lamp",           39.99),
    ("Cable Organizer",     14.99),
    ("Mouse Pad XL",        19.99),
    ("Smart Plug (4-pack)", 29.99),
]
STATUSES = ["pending","shipped","delivered","cancelled","returned"]
STATUS_WEIGHTS = [0.10, 0.20, 0.45, 0.15, 0.10]

def uid(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:8].upper()}"

def rand_date(days_ago_max=180, days_ago_min=0):
    d = datetime.now() - timedelta(days=random.randint(days_ago_min, days_ago_max))
    return d.strftime("%Y-%m-%d %H:%M:%S")

def seed():
    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA.read_text())

    # ── policies ───────────────────────────────────────────
    conn.executemany("INSERT INTO policies VALUES (?,?,?)", [
        ("POL-001", "refund",
         "Refunds are accepted within 30 days of delivery for unused items. "
         "Digital products are non-refundable. Refund amount equals the original "
         "payment minus any shipping fees. Processing takes 3–5 business days."),
        ("POL-002", "shipping",
         "Standard shipping: 5–7 business days. Express: 2–3 days. Overnight: next day. "
         "Free standard shipping on orders over $50. Shipped orders cannot have their "
         "address updated. Unshipped (pending) orders can be updated up to 1 hour before dispatch."),
        ("POL-003", "cancellation",
         "Orders can be cancelled within 1 hour of placement if still in 'pending' status. "
         "Shipped or delivered orders cannot be cancelled — initiate a return instead. "
         "Cancellations are fully refunded within 2 business days."),
        ("POL-004", "returns",
         "Items can be returned within 30 days of delivery. Items must be in original packaging. "
         "Customer pays return shipping unless item is defective. Refund issued after item inspection."),
    ])

    # ── customers + addresses + orders ────────────────────
    used_emails = set()
    customers   = []

    # Force a few duplicate first names for ambiguity tests
    names = [(fn, ln) for fn in FIRST_NAMES for ln in random.sample(LAST_NAMES, 2)]
    random.shuffle(names)
    # Ensure multiple Johns and Sarahs
    for fn in ("John","Sarah","Amy"):
        for _ in range(2):
            names.insert(0, (fn, random.choice(LAST_NAMES)))
    names = names[:60]   # 60 customers

    for fn, ln in names:
        cid   = uid("CUST-")
        email = f"{fn.lower()}.{ln.lower()}{random.randint(1,99)}@example.com"
        if email in used_emails:
            email = f"{fn.lower()}{random.randint(100,999)}@example.com"
        used_emails.add(email)
        phone = f"555-{random.randint(100,999)}-{random.randint(1000,9999)}"
        conn.execute("INSERT INTO customers VALUES (?,?,?,?,?)",
                     (cid, f"{fn} {ln}", email, phone, rand_date(365, 200)))
        customers.append((cid, fn, ln))

        # 1–2 addresses per customer
        for i in range(random.randint(1, 2)):
            aid = uid("ADDR-")
            conn.execute("INSERT INTO addresses VALUES (?,?,?,?,?,?,?,?,?)", (
                aid, cid,
                f"{random.randint(1,9999)} {random.choice(['Oak','Main','Elm','Park'])} St",
                f"Apt {random.randint(1,50)}" if random.random() < 0.3 else None,
                random.choice(["Austin","Seattle","Chicago","Denver","Miami","Portland"]),
                random.choice(["TX","WA","IL","CO","FL","OR"]),
                f"{random.randint(10000,99999)}",
                "US", 1 if i == 0 else 0,
            ))

        # 1–5 orders per customer
        for _ in range(random.randint(1, 5)):
            oid    = uid("ORD-")
            status = random.choices(STATUSES, STATUS_WEIGHTS)[0]
            odate  = rand_date(180, 1)

            # shipping address only for non-pending orders
            ship_addr = None
            if status != "pending":
                row = conn.execute(
                    "SELECT address_id FROM addresses WHERE customer_id=? LIMIT 1", (cid,)
                ).fetchone()
                ship_addr = row[0] if row else None

            conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                         (oid, cid, status, ship_addr, odate, odate))

            # 1–3 items per order
            for _ in range(random.randint(1, 3)):
                product, price = random.choice(PRODUCTS)
                qty = random.randint(1, 3)
                conn.execute("INSERT INTO order_items VALUES (?,?,?,?,?)",
                             (uid("ITEM-"), oid, product, qty, price))

            # payment for non-cancelled
            total = sum(
                r[0] * r[1] for r in
                conn.execute("SELECT quantity, unit_price FROM order_items WHERE order_id=?", (oid,))
            )
            if status != "cancelled":
                conn.execute("INSERT INTO payments VALUES (?,?,?,?,?)",
                             (uid("PAY-"), oid, round(total, 2), "completed", odate))

            # refund for returned orders
            if status == "returned":
                conn.execute("INSERT INTO refunds VALUES (?,?,?,?,?,?)",
                             (uid("REF-"), oid, round(total, 2),
                              "Customer return", "completed", odate))

    conn.commit()
    conn.close()

    # summary
    c = sqlite3.connect(DB_PATH)
    print("Database seeded:")
    for table in ["customers","orders","payments","refunds","addresses","policies"]:
        n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<12} {n} rows")
    c.close()

if __name__ == "__main__":
    seed()
