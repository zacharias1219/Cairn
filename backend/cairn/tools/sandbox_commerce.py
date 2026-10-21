"""Acme Commerce sandbox: a mock MCP server for testing and demos (F5).

It speaks MCP's JSON-RPC methods (``initialize``, ``tools/list``,
``tools/call``) over HTTP at ``/sandbox/mcp/commerce`` and is also callable
in-process. Write calls honour the idempotency key in ``_meta``, the same
way a real payments API would.
"""

from __future__ import annotations

import copy
import contextvars
import datetime as dt
import threading
import uuid
from typing import Any

ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"}, "status": {"type": "string"},
        "customer_email": {"type": "string"}, "items": {"type": "array"},
        "total": {"type": "number"}, "currency": {"type": "string"},
        "placed_at": {"type": "string"}, "delivered_at": {"type": ["string", "null"]},
        "days_since_delivery": {"type": ["integer", "null"]}, "refunded": {"type": "boolean"},
        "refunded_amount": {"type": "number"}, "shipping_address": {"type": "string"},
        "carrier": {"type": ["string", "null"]}, "tracking": {"type": ["string", "null"]},
        "eta": {"type": ["string", "null"]},
    },
    "required": ["order_id", "status", "total"],
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_order", "title": "Look up order",
        "description": "Fetch an order's status, items, totals, delivery and refund state by order ID.",
        "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string", "pattern": "^A\\d{4}$"}},
                        "required": ["order_id"], "additionalProperties": False},
        "outputSchema": ORDER_SCHEMA, "risk_tier": "low", "is_write": False, "pap_exposed": True,
    },
    {
        "name": "verify_customer", "title": "Verify customer",
        "description": "Check that an email address owns an order. Used to verify identity before account changes.",
        "inputSchema": {"type": "object", "properties": {
            "email": {"type": "string", "format": "email"}, "order_id": {"type": "string", "pattern": "^A\\d{4}$"}},
            "required": ["email", "order_id"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {"verified": {"type": "boolean"}}, "required": ["verified"]},
        "risk_tier": "low", "is_write": False, "pap_exposed": False,
    },
    {
        "name": "issue_refund", "title": "Issue refund",
        "description": "Refund an amount to the original payment method for an order.",
        "inputSchema": {"type": "object", "properties": {
            "order_id": {"type": "string", "pattern": "^A\\d{4}$"},
            "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 10000},
            "reason": {"type": "string", "minLength": 3, "maxLength": 300}},
            "required": ["order_id", "amount", "reason"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "refund_id": {"type": "string"}, "order_id": {"type": "string"}, "amount": {"type": "number"},
            "status": {"type": "string"}, "expected_days": {"type": "string"}},
            "required": ["refund_id", "amount", "status"]},
        "risk_tier": "medium", "is_write": True, "pap_exposed": True,
    },
    {
        "name": "lookup_subscription", "title": "Look up subscription",
        "description": "Find the Trail Club subscription for an email address.",
        "inputSchema": {"type": "object", "properties": {"email": {"type": "string", "format": "email"}},
                        "required": ["email"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "subscription_id": {"type": ["string", "null"]}, "plan": {"type": ["string", "null"]},
            "status": {"type": "string"}, "renews_at": {"type": ["string", "null"]},
            "monthly_price": {"type": ["number", "null"]}}, "required": ["status"]},
        "risk_tier": "low", "is_write": False, "pap_exposed": True,
    },
    {
        "name": "cancel_subscription", "title": "Cancel subscription",
        "description": "Cancel a Trail Club subscription at the end of the current period.",
        "inputSchema": {"type": "object", "properties": {
            "subscription_id": {"type": "string", "pattern": "^SUB-\\d{4}$"},
            "reason": {"type": "string", "minLength": 3, "maxLength": 300}},
            "required": ["subscription_id", "reason"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "subscription_id": {"type": "string"}, "status": {"type": "string"},
            "access_until": {"type": "string"}}, "required": ["subscription_id", "status"]},
        "risk_tier": "medium", "is_write": True, "pap_exposed": True,
    },
    {
        "name": "update_shipping_address", "title": "Update shipping address",
        "description": "Change the shipping address of an order that has not shipped yet.",
        "inputSchema": {"type": "object", "properties": {
            "order_id": {"type": "string", "pattern": "^A\\d{4}$"},
            "address": {"type": "string", "minLength": 10, "maxLength": 300}},
            "required": ["order_id", "address"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "order_id": {"type": "string"}, "shipping_address": {"type": "string"}, "status": {"type": "string"}},
            "required": ["order_id", "status"]},
        "risk_tier": "medium", "is_write": True, "pap_exposed": False,
    },
    {
        "name": "apply_goodwill_credit", "title": "Apply goodwill credit",
        "description": "Add store credit to a customer account as a goodwill gesture.",
        "inputSchema": {"type": "object", "properties": {
            "email": {"type": "string", "format": "email"},
            "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 200},
            "reason": {"type": "string", "minLength": 3, "maxLength": 300}},
            "required": ["email", "amount", "reason"], "additionalProperties": False},
        "outputSchema": {"type": "object", "properties": {
            "credit_id": {"type": "string"}, "amount": {"type": "number"}, "status": {"type": "string"}},
            "required": ["credit_id", "status"]},
        "risk_tier": "high", "is_write": True, "pap_exposed": False,
    },
]


def _days_ago(n: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).replace(microsecond=0).isoformat()


def _seed_orders() -> dict[str, dict]:
    def order(oid, email, status, items, total, placed, delivered=None, refunded=0.0, eta=None,
              address="18 Ridge Rd, Boulder, CO 80302", carrier=None, tracking=None):
        return {
            "order_id": oid, "customer_email": email, "status": status, "items": items,
            "total": total, "currency": "USD", "placed_at": _days_ago(placed),
            "delivered_at": _days_ago(delivered) if delivered is not None else None,
            "delivered_days": delivered, "refunded_amount": refunded,
            "shipping_address": address, "eta": eta, "carrier": carrier, "tracking": tracking,
        }

    return {o["order_id"]: o for o in [
        order("A1001", "maya.chen@example.com", "delivered",
              [{"sku": "PK-40", "name": "Trailhead 40L Pack", "qty": 1, "price": 84.0}], 84.0, 9, 5),
        order("A1002", "maya.chen@example.com", "shipped",
              [{"sku": "BT-02", "name": "Ridgeline Bottle", "qty": 2, "price": 21.25}], 42.5, 3,
              eta="Thursday", carrier="UPS", tracking="1Z84A0F20398"),
        order("A1003", "jordan.lee@example.com", "delivered",
              [{"sku": "JK-11", "name": "Alpine Shell Jacket", "qty": 1, "price": 129.0}], 129.0, 52, 45),
        order("A1004", "sam.patel@example.com", "delivered",
              [{"sku": "TN-2P", "name": "Basecamp 2P Tent", "qty": 1, "price": 249.0}], 249.0, 14, 10),
        order("A1005", "sam.patel@example.com", "processing",
              [{"sku": "SL-20", "name": "Summit 20° Sleeping Bag", "qty": 1, "price": 189.0}], 189.0, 1,
              eta="next week"),
        order("A1006", "alex.kim@example.com", "delivered",
              [{"sku": "HT-01", "name": "Merino Trail Hat", "qty": 1, "price": 32.0}], 32.0, 6, 3, refunded=32.0),
        order("A1007", "priya.nair@example.com", "delivered",
              [{"sku": "ST-09", "name": "Carbon Trekking Poles", "qty": 1, "price": 98.0},
               {"sku": "SK-03", "name": "Wool Hiking Socks (3-pack)", "qty": 1, "price": 27.0}], 125.0, 8, 4),
        order("A1008", "leo.garcia@example.com", "delivered",
              [{"sku": "HL-05", "name": "Beacon Headlamp", "qty": 1, "price": 45.0}], 45.0, 20, 16),
    ]}


SUBSCRIPTIONS = {
    "jordan.lee@example.com": {"subscription_id": "SUB-2001", "plan": "Trail Club", "status": "active",
                               "monthly_price": 9.0},
    "priya.nair@example.com": {"subscription_id": "SUB-2002", "plan": "Trail Club", "status": "active",
                               "monthly_price": 9.0},
    "maya.chen@example.com": {"subscription_id": "SUB-2003", "plan": "Trail Club Plus", "status": "active",
                              "monthly_price": 15.0},
}


class CommerceSandbox:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.orders = _seed_orders()
            self.subs = copy.deepcopy(SUBSCRIPTIONS)
            self.idempotent: dict[str, dict] = {}
            self.refunds: list[dict] = []
            self.credits: list[dict] = []

    # ------------------------------------------------------- json-rpc
    def handle(self, req: dict) -> dict:
        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if method == "initialize":
            return _ok(rid, {"protocolVersion": "2025-06-18", "serverInfo": {"name": "acme-commerce-sandbox",
                                                                           "version": "1.0"},
                             "capabilities": {"tools": {}}})
        if method == "tools/list":
            return _ok(rid, {"tools": [{k: v for k, v in t.items() if k in
                                        ("name", "title", "description", "inputSchema", "outputSchema")}
                                       for t in TOOLS]})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            key = (params.get("_meta") or {}).get("idempotency_key")
            try:
                with self._lock:
                    if key and key in self.idempotent:
                        return _ok(rid, self.idempotent[key])
                    result = getattr(self, f"_t_{name}")(args)
                    payload = {"content": [{"type": "text", "text": str(result)}],
                               "structuredContent": result, "isError": False}
                    if key:
                        self.idempotent[key] = payload
                return _ok(rid, payload)
            except AttributeError:
                return _err(rid, -32601, f"unknown tool {name}")
            except ToolError as e:
                return _ok(rid, {"content": [{"type": "text", "text": str(e)}],
                                 "structuredContent": {"error": str(e)}, "isError": True})
        return _err(rid, -32601, f"unknown method {method}")

    # -------------------------------------------------------- tools
    def _order(self, oid: str) -> dict:
        o = self.orders.get(oid)
        if not o:
            raise ToolError(f"order {oid} not found")
        return o

    def _view(self, o: dict) -> dict:
        v = {k: val for k, val in o.items() if k != "delivered_days"}
        v["days_since_delivery"] = o["delivered_days"]
        v["refunded"] = o["refunded_amount"] > 0
        return v

    def _t_lookup_order(self, a: dict) -> dict:
        return self._view(self._order(a["order_id"]))

    def _t_verify_customer(self, a: dict) -> dict:
        o = self.orders.get(a["order_id"])
        return {"verified": bool(o and o["customer_email"].lower() == a["email"].lower())}

    def _t_issue_refund(self, a: dict) -> dict:
        o = self._order(a["order_id"])
        if a["amount"] > o["total"] - o["refunded_amount"] + 1e-9:
            raise ToolError("refund exceeds the refundable balance")
        o["refunded_amount"] = round(o["refunded_amount"] + a["amount"], 2)
        refund = {"refund_id": "RF-" + uuid.uuid4().hex[:8].upper(), "order_id": o["order_id"],
                  "amount": a["amount"], "status": "issued", "expected_days": "5-10 business days"}
        self.refunds.append(refund)
        return refund

    def _t_lookup_subscription(self, a: dict) -> dict:
        s = self.subs.get(a["email"].lower())
        if not s:
            return {"subscription_id": None, "plan": None, "status": "none", "renews_at": None,
                    "monthly_price": None}
        return {**s, "renews_at": (dt.date.today() + dt.timedelta(days=12)).isoformat()}

    def _t_cancel_subscription(self, a: dict) -> dict:
        for s in self.subs.values():
            if s["subscription_id"] == a["subscription_id"]:
                s["status"] = "canceled"
                return {"subscription_id": s["subscription_id"], "status": "canceled",
                        "access_until": (dt.date.today() + dt.timedelta(days=12)).isoformat()}
        raise ToolError(f"subscription {a['subscription_id']} not found")

    def _t_update_shipping_address(self, a: dict) -> dict:
        o = self._order(a["order_id"])
        if o["status"] not in ("processing",):
            raise ToolError(f"order {o['order_id']} has already {o['status']}")
        o["shipping_address"] = a["address"]
        return {"order_id": o["order_id"], "shipping_address": a["address"], "status": "updated"}

    def _t_apply_goodwill_credit(self, a: dict) -> dict:
        c = {"credit_id": "CR-" + uuid.uuid4().hex[:8].upper(), "amount": a["amount"], "status": "applied"}
        self.credits.append(c)
        return c


class ToolError(Exception):
    pass


def _ok(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


SANDBOX = CommerceSandbox()
SANDBOX_URL = "sandbox://commerce"

# The eval harness gives every case its own fresh sandbox, so cases never
# see each other's refunds and live demo traffic is untouched.
current: contextvars.ContextVar[CommerceSandbox] = contextvars.ContextVar("commerce_sandbox", default=SANDBOX)
