"""
7 tools for the Customer Operations Agent.
Read tools: search_customer, get_orders, get_order, lookup_policy
Write tools: refund_order, update_shipping_address, send_customer_message
"""
import json, sqlite3, uuid, random
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "database" / "ops.db"

# injected by the evaluator for failure simulation
_FAIL_TOOL: str | None = None
_FAIL_PROBABILITY: float = 0.0


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _maybe_fail(tool_name: str):
    """Simulate transient 503 for tool failure tests."""
    if _FAIL_TOOL == tool_name and random.random() < _FAIL_PROBABILITY:
        raise RuntimeError(f"503 Service Unavailable — {tool_name} timed out")


# ── Tool 1 ────────────────────────────────────────────────
def search_customer(name: str = None, email: str = None, phone: str = None) -> str:
    """
    Search for a customer by name, email, or phone.
    Returns matching customers with their customer_id.
    Always call this first before any order operations.
    """
    _maybe_fail("search_customer")
    if not any([name, email, phone]):
        return json.dumps({"error": "Provide at least one of: name, email, phone"})

    conn = _conn()
    conditions, params = [], []
    if name:
        conditions.append("LOWER(name) LIKE ?")
        params.append(f"%{name.lower()}%")
    if email:
        conditions.append("LOWER(email) = ?")
        params.append(email.lower())
    if phone:
        conditions.append("phone = ?")
        params.append(phone)

    rows = conn.execute(
        f"SELECT customer_id, name, email, phone FROM customers WHERE {' OR '.join(conditions)}",
        params
    ).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"matches": [], "message": "No customers found."})
    results = [dict(r) for r in rows]
    if len(results) > 1:
        return json.dumps({
            "matches": results,
            "message": f"{len(results)} customers found — clarify which one before proceeding."
        })
    return json.dumps({"matches": results})


# ── Tool 2 ────────────────────────────────────────────────
def get_orders(customer_id: str) -> str:
    """
    Return all orders for a customer, newest first.
    Includes order_id, status, created_at, and item count.
    """
    _maybe_fail("get_orders")
    conn = _conn()
    rows = conn.execute("""
        SELECT o.order_id, o.status, o.created_at,
               COUNT(i.item_id) AS item_count,
               ROUND(SUM(i.quantity * i.unit_price), 2) AS total
        FROM orders o
        LEFT JOIN order_items i ON o.order_id = i.order_id
        WHERE o.customer_id = ?
        GROUP BY o.order_id
        ORDER BY o.created_at DESC
    """, (customer_id,)).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"orders": [], "message": "No orders found for this customer."})
    return json.dumps({"orders": [dict(r) for r in rows]})


# ── Tool 3 ────────────────────────────────────────────────
def get_order(order_id: str) -> str:
    """
    Return complete details for a single order: items, payment, refunds, shipping address.
    """
    _maybe_fail("get_order")
    conn = _conn()

    order = conn.execute("""
        SELECT o.*, c.name AS customer_name, c.email AS customer_email
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE o.order_id = ?
    """, (order_id,)).fetchone()

    if not order:
        conn.close()
        return json.dumps({"error": f"Order {order_id} not found."})

    items = conn.execute(
        "SELECT product, quantity, unit_price FROM order_items WHERE order_id = ?", (order_id,)
    ).fetchall()

    payment = conn.execute(
        "SELECT amount, status, paid_at FROM payments WHERE order_id = ?", (order_id,)
    ).fetchone()

    refunds = conn.execute(
        "SELECT refund_id, amount, reason, status, created_at FROM refunds WHERE order_id = ?",
        (order_id,)
    ).fetchall()

    address = None
    if order["shipping_address"]:
        row = conn.execute(
            "SELECT line1, line2, city, state, zip FROM addresses WHERE address_id = ?",
            (order["shipping_address"],)
        ).fetchone()
        if row:
            address = dict(row)

    conn.close()
    return json.dumps({
        "order_id":       order["order_id"],
        "customer_name":  order["customer_name"],
        "customer_email": order["customer_email"],
        "status":         order["status"],
        "created_at":     order["created_at"],
        "shipping_address": address,
        "items":          [dict(i) for i in items],
        "payment":        dict(payment) if payment else None,
        "refunds":        [dict(r) for r in refunds],
        "total":          round(sum(i["quantity"] * i["unit_price"] for i in items), 2),
    }, default=str)


# ── Tool 4 ────────────────────────────────────────────────
def lookup_policy(topic: str) -> str:
    """
    Look up company policy on: refund, shipping, cancellation, returns.
    Always call this before taking any action that could be policy-restricted.
    """
    _maybe_fail("lookup_policy")
    conn = _conn()
    row = conn.execute(
        "SELECT content FROM policies WHERE LOWER(name) LIKE ?",
        (f"%{topic.lower()}%",)
    ).fetchone()
    conn.close()

    if not row:
        return json.dumps({"error": f"No policy found for '{topic}'. "
                                     "Available: refund, shipping, cancellation, returns."})
    return json.dumps({"topic": topic, "policy": row["content"]})


# ── Tool 5 ────────────────────────────────────────────────
def refund_order(order_id: str, amount: float, reason: str) -> str:
    """
    Issue a refund for an order. Only call after verifying policy eligibility.
    The order must exist and must not already have a completed refund.
    """
    _maybe_fail("refund_order")
    conn = _conn()

    order = conn.execute(
        "SELECT status FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    if not order:
        conn.close()
        return json.dumps({"error": f"Order {order_id} not found."})

    existing = conn.execute(
        "SELECT refund_id FROM refunds WHERE order_id = ? AND status = 'completed'",
        (order_id,)
    ).fetchone()
    if existing:
        conn.close()
        return json.dumps({"error": f"Order {order_id} already has a completed refund."})

    payment = conn.execute(
        "SELECT amount FROM payments WHERE order_id = ?", (order_id,)
    ).fetchone()
    if payment and amount > payment["amount"]:
        conn.close()
        return json.dumps({"error": f"Refund amount ${amount} exceeds payment ${payment['amount']}."})

    rid = f"REF-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(
        "INSERT INTO refunds VALUES (?,?,?,?,?,?)",
        (rid, order_id, amount, reason, "completed", datetime.now().isoformat())
    )
    conn.execute(
        "UPDATE orders SET status='returned', updated_at=? WHERE order_id=?",
        (datetime.now().isoformat(), order_id)
    )
    conn.commit()
    conn.close()
    return json.dumps({"success": True, "refund_id": rid, "amount": amount, "order_id": order_id})


# ── Tool 6 ────────────────────────────────────────────────
def update_shipping_address(order_id: str, line1: str, city: str,
                            state: str, zip: str, line2: str = None) -> str:
    """
    Update the shipping address for an unshipped (pending) order.
    Cannot update address for shipped or delivered orders.
    """
    _maybe_fail("update_shipping_address")
    conn = _conn()

    order = conn.execute(
        "SELECT status, customer_id FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    if not order:
        conn.close()
        return json.dumps({"error": f"Order {order_id} not found."})
    if order["status"] != "pending":
        conn.close()
        return json.dumps({
            "error": f"Cannot update address — order is '{order['status']}'. "
                     "Address can only be changed on pending orders."
        })

    aid = f"ADDR-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(
        "INSERT INTO addresses VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, order["customer_id"], line1, line2, city, state, zip, "US", 0)
    )
    conn.execute(
        "UPDATE orders SET shipping_address=?, updated_at=? WHERE order_id=?",
        (aid, datetime.now().isoformat(), order_id)
    )
    conn.commit()
    conn.close()
    return json.dumps({"success": True, "order_id": order_id,
                       "new_address": f"{line1}, {city}, {state} {zip}"})


# ── Tool 7 ────────────────────────────────────────────────
def send_customer_message(customer_id: str, subject: str, body: str) -> str:
    """
    Send a simulated email/message to a customer.
    Use to confirm actions (refunds, address changes) or answer questions.
    """
    _maybe_fail("send_customer_message")
    conn = _conn()
    row = conn.execute(
        "SELECT name, email FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    conn.close()

    if not row:
        return json.dumps({"error": f"Customer {customer_id} not found."})

    # Simulated — just log it
    msg_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
    print(f"\n📧  [{msg_id}] To: {row['name']} <{row['email']}>")
    print(f"    Subject: {subject}")
    print(f"    Body: {body[:120]}{'...' if len(body) > 120 else ''}\n")
    return json.dumps({"success": True, "message_id": msg_id,
                       "to": row["email"], "subject": subject})


# ── Tool registry (for the agent) ─────────────────────────
TOOLS = [
    {
        "name": "search_customer",
        "description": search_customer.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "name":  {"type": "string", "description": "Customer full or partial name"},
                "email": {"type": "string", "description": "Customer email address"},
                "phone": {"type": "string", "description": "Customer phone number"},
            },
        },
    },
    {
        "name": "get_orders",
        "description": get_orders.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_order",
        "description": get_order.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "lookup_policy",
        "description": lookup_policy.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "description": "Policy topic: refund, shipping, cancellation, returns"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "refund_order",
        "description": refund_order.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount":   {"type": "number", "description": "Refund amount in USD"},
                "reason":   {"type": "string"},
            },
            "required": ["order_id", "amount", "reason"],
        },
    },
    {
        "name": "update_shipping_address",
        "description": update_shipping_address.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "line1":    {"type": "string"},
                "line2":    {"type": "string"},
                "city":     {"type": "string"},
                "state":    {"type": "string"},
                "zip":      {"type": "string"},
            },
            "required": ["order_id", "line1", "city", "state", "zip"],
        },
    },
    {
        "name": "send_customer_message",
        "description": send_customer_message.__doc__.strip(),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string"},
                "subject":     {"type": "string"},
                "body":        {"type": "string"},
            },
            "required": ["customer_id", "subject", "body"],
        },
    },
]

TOOL_MAP = {
    "search_customer":        search_customer,
    "get_orders":             get_orders,
    "get_order":              get_order,
    "lookup_policy":          lookup_policy,
    "refund_order":           refund_order,
    "update_shipping_address": update_shipping_address,
    "send_customer_message":  send_customer_message,
}
