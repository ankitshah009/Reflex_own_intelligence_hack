"""Fictional release incidents with private behavioral checks.

Public projections contain only the broken source, reproduction, and expected
business behavior. Reference implementations and check answers stay private.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_PUBLIC_FIELDS = (
    "id", "title", "service", "description", "filename", "source", "initial_state",
    "actions", "reproduction", "expected_behavior", "source_kind", "language",
)


def public_case(case: dict[str, Any]) -> dict[str, Any]:
    return deepcopy({field: case[field] for field in _PUBLIC_FIELDS if field in case})


def _state() -> dict[str, Any]:
    return {"orders": [], "inventory": {"widget": 12, "gadget": 8}, "refunds": [], "balance_cents": 9600, "processed": {}}


def _field(event: dict[str, Any], name: str) -> Any:
    value: Any = event
    for part in name.split("."):
        value = value[part]
    return value


def _oracle(state: dict[str, Any], event: dict[str, Any], *, family: str, keys: tuple[str, ...], nested: str = "") -> dict[str, Any]:
    """Trusted specification; candidate source is never evaluated here."""
    key = ":".join(str(_field(event, name)) for name in keys)
    if key in state["processed"]:
        return deepcopy(state["processed"][key])
    value = event[nested] if nested else event
    if family == "order":
        state["inventory"][value["sku"]] -= value["quantity"]
        state["orders"].append({"id": value["order_id"], "sku": value["sku"], "quantity": value["quantity"], "total_cents": value["total_cents"]})
        state["balance_cents"] += value["total_cents"]
        response = {"order_id": value["order_id"], "status": "accepted"}
    elif family == "delta":
        state["inventory"][value["sku"]] += value["delta"]
        response = {"sku": value["sku"], "quantity": state["inventory"][value["sku"]]}
    elif family == "refund":
        state["balance_cents"] -= value["amount_cents"]
        state["refunds"].append({"id": value["refund_id"], "order_id": value["order_id"], "amount_cents": value["amount_cents"]})
        response = {"refund_id": value["refund_id"], "refunded_cents": value["amount_cents"]}
    elif family == "cancel":
        state["inventory"][value["sku"]] += value["quantity"]
        for order in state["orders"]:
            if order["id"] == value["order_id"]:
                order["status"] = "cancelled"
        response = {"order_id": value["order_id"], "status": "cancelled"}
    elif family == "renewal":
        state["balance_cents"] += value["total_cents"]
        state["orders"].append({"id": value["invoice_id"], "subscription_id": value["subscription_id"], "total_cents": value["total_cents"]})
        response = {"invoice_id": value["invoice_id"], "charged_cents": value["total_cents"]}
    else:
        raise ValueError("Unknown trusted fixture family")
    state["processed"][key] = deepcopy(response)
    return response


def _case(identifier: str, title: str, service: str, description: str, source: str, reference: str, first: dict[str, Any], second: dict[str, Any], *, family: str, keys: tuple[str, ...], behavior: str, split: str = "train", nested: str = "", initial: dict[str, Any] | None = None, replay: dict[str, Any] | None = None) -> dict[str, Any]:
    initial = deepcopy(initial or _state())
    replay = deepcopy(replay or first)
    scenarios = [
        ("First delivery preserves the business contract", [first]),
        ("A repeated operation does not duplicate effects", [first, replay]),
        ("Distinct operations both succeed", [first, second]),
        ("Delayed retries return the original result", [first, second, replay, second]),
    ]
    checks = []
    for name, events in scenarios:
        expected = deepcopy(initial)
        results = [_oracle(expected, deepcopy(event), family=family, keys=keys, nested=nested) for event in events]
        checks.append({"name": name, "initial_state": deepcopy(initial), "events": deepcopy(events), "expected_state": expected, "expected_results": results})
    return {
        "id": identifier, "title": title, "service": service,
        "description": description + " Fictional sample incident; no production data is included.",
        "filename": "handler.py", "source": source.strip() + "\n", "initial_state": initial,
        "actions": [
            {"id": "first", "label": "Send first event", "payload": deepcopy(first)},
            {"id": "replay", "label": "Replay the same operation", "payload": deepcopy(replay)},
            {"id": "second", "label": "Send a distinct operation", "payload": deepcopy(second)},
        ],
        "reproduction": [deepcopy(first), deepcopy(replay)],
        "expected_behavior": behavior + " Keep the existing state schema. Store each successful JSON response in state['processed'] under that operation key and return the stored response on replay. Execution is sequential; this fixture does not model database transaction races.",
        "source_kind": "sample", "language": "python", "_split": split,
        "_checks": checks, "_reference_code": reference.strip() + "\n",
    }


_ORDER = '''def apply(state, event):
    key = event["event_id"]
    sku = event["sku"]
    state["inventory"][sku] -= event["quantity"]
    state["orders"].append({"id": event["order_id"], "sku": sku, "quantity": event["quantity"], "total_cents": event["total_cents"]})
    state["balance_cents"] += event["total_cents"]
    response = {"order_id": event["order_id"], "status": "accepted"}
    state["processed"][key] = response
    return response
'''
_ORDER_FIXED = _ORDER.replace('    sku = event["sku"]', '    if key in state["processed"]:\n        return state["processed"][key]\n    sku = event["sku"]')

_INVENTORY = '''def apply(state, event):
    key = event["update_id"]
    sku = event["sku"]
    state["inventory"][sku] = state["inventory"][sku] + event["delta"]
    if key in state["processed"]:
        return state["processed"][key]
    response = {"sku": sku, "quantity": state["inventory"][sku]}
    state["processed"][key] = response
    return response
'''
_INVENTORY_FIXED = '''def apply(state, event):
    key = event["update_id"]
    if key in state["processed"]:
        return state["processed"][key]
    sku = event["sku"]
    state["inventory"][sku] += event["delta"]
    response = {"sku": sku, "quantity": state["inventory"][sku]}
    state["processed"][key] = response
    return response
'''

_REFUND = '''def apply(state, event):
    key = event["delivery_id"]
    if key in state["processed"]:
        return state["processed"][key]
    state["balance_cents"] -= event["amount_cents"]
    state["refunds"].append({"id": event["refund_id"], "order_id": event["order_id"], "amount_cents": event["amount_cents"]})
    result = {"refund_id": event["refund_id"], "refunded_cents": event["amount_cents"]}
    state["processed"][key] = result
    return result
'''
_REFUND_FIXED = _REFUND.replace('key = event["delivery_id"]', 'key = event["refund_id"]')

_TENANT_ORDER = '''def apply(state, event):
    key = event["request_id"]
    if key in state["processed"]:
        return state["processed"][key]
    order = {"id": event["order_id"], "sku": event["sku"], "quantity": event["quantity"], "total_cents": event["total_cents"]}
    state["orders"].append(order)
    state["inventory"][order["sku"]] -= order["quantity"]
    state["balance_cents"] += order["total_cents"]
    state["processed"][key] = {"order_id": order["id"], "status": "accepted"}
    return state["processed"][key]
'''
_TENANT_ORDER_FIXED = _TENANT_ORDER.replace('key = event["request_id"]', 'key = event["tenant_id"] + ":" + event["request_id"]')

_SKU_UPDATE = '''def apply(state, event):
    sku = event["sku"]
    key = sku
    if state["processed"].get(key) is not None:
        return state["processed"][key]
    quantity = state["inventory"].get(sku, 0) + event["delta"]
    state["inventory"][sku] = quantity
    result = {"sku": sku, "quantity": quantity}
    state["processed"][key] = result
    return result
'''
_SKU_UPDATE_FIXED = _SKU_UPDATE.replace('    key = sku', '    key = event["adjustment_id"]')

_CANCEL = '''def apply(state, event):
    key = event["cancellation_id"]
    for order in state["orders"]:
        if order["id"] == event["order_id"]:
            order["status"] = "cancelled"
    state["inventory"][event["sku"]] += event["quantity"]
    result = {"order_id": event["order_id"], "status": "cancelled"}
    state["processed"][key] = result
    return result
'''
_CANCEL_FIXED = _CANCEL.replace('    for order in state["orders"]:', '    if key in state["processed"]:\n        return state["processed"][key]\n    for order in state["orders"]:')
_CANCEL_INITIAL = {**_state(), "orders": [{"id": "ord-201", "status": "paid"}, {"id": "ord-202", "status": "paid"}]}

_TRAIN = [
    _case("repair-order-replay", "One click. Two orders.", "Checkout", "A payment webhook retry creates a duplicate order and takes inventory twice.", _ORDER, _ORDER_FIXED,
          {"event_id": "checkout-100", "order_id": "ord-100", "sku": "widget", "quantity": 2, "total_cents": 2400},
          {"event_id": "checkout-101", "order_id": "ord-101", "sku": "gadget", "quantity": 1, "total_cents": 1800},
          family="order", keys=("event_id",), behavior="A checkout event_id represents one paid order. Replaying it must not create another order, charge, or stock deduction."),
    _case("repair-stock-replay", "Stock moves twice on retry", "Inventory", "The update handler detects a duplicate after it has already changed the stock count.", _INVENTORY, _INVENTORY_FIXED,
          {"update_id": "stock-20", "sku": "widget", "delta": -3}, {"update_id": "stock-21", "sku": "widget", "delta": 5},
          family="delta", keys=("update_id",), behavior="Apply each update_id once. Different update IDs for the same SKU must both apply. Replays return the originally recorded quantity."),
    _case("repair-refund-retry", "Refund delivered. Then delivered again.", "Refunds", "The provider changes the delivery identifier when retrying the same logical refund.", _REFUND, _REFUND_FIXED,
          {"delivery_id": "delivery-1", "refund_id": "ref-90", "order_id": "ord-90", "amount_cents": 1200},
          {"delivery_id": "delivery-3", "refund_id": "ref-91", "order_id": "ord-90", "amount_cents": 600},
          replay={"delivery_id": "delivery-2", "refund_id": "ref-90", "order_id": "ord-90", "amount_cents": 1200},
          family="refund", keys=("refund_id",), behavior="Use refund_id as the operation key. A new delivery_id for the same refund must not debit the balance again. Distinct partial refunds on one order remain valid."),
    _case("repair-tenant-checkout", "A second shop loses its order", "Checkout", "Two shops may use the same request ID. A global request key suppresses a legitimate second order.", _TENANT_ORDER, _TENANT_ORDER_FIXED,
          {"tenant_id": "shop-a", "request_id": "req-7", "order_id": "ord-a", "sku": "widget", "quantity": 1, "total_cents": 1200},
          {"tenant_id": "shop-b", "request_id": "req-7", "order_id": "ord-b", "sku": "gadget", "quantity": 2, "total_cents": 3600},
          family="order", keys=("tenant_id", "request_id"), behavior="Operation keys are tenant_id + ':' + request_id. Deduplicate within a tenant, while allowing another tenant to use the same request ID."),
    _case("repair-stock-overdedupe", "The next delivery disappears", "Inventory", "The handler remembers that a SKU was updated and incorrectly ignores later deliveries for it.", _SKU_UPDATE, _SKU_UPDATE_FIXED,
          {"adjustment_id": "adj-11", "sku": "widget", "delta": 4}, {"adjustment_id": "adj-12", "sku": "widget", "delta": -2},
          family="delta", keys=("adjustment_id",), behavior="Use adjustment_id as the operation key, not the SKU. Independent stock adjustments must apply even when they target the same item."),
    _case("repair-cancel-replay", "Cancelled stock returns twice", "Orders", "A retried cancellation restores the same reserved inventory more than once.", _CANCEL, _CANCEL_FIXED,
          {"cancellation_id": "cancel-201", "order_id": "ord-201", "sku": "widget", "quantity": 2},
          {"cancellation_id": "cancel-202", "order_id": "ord-202", "sku": "gadget", "quantity": 1},
          family="cancel", keys=("cancellation_id",), initial=_CANCEL_INITIAL,
          behavior="Use cancellation_id as the operation key. Mark the matching order cancelled and release its stock exactly once. Other cancellations must still work."),
]


_RENEWAL = '''def apply(state, event):
    invoice = event["invoice"]
    key = event["webhook_id"]
    existing = state["processed"].get(key)
    if existing is not None:
        return existing
    state["orders"].append({"id": invoice["invoice_id"], "subscription_id": invoice["subscription_id"], "total_cents": invoice["total_cents"]})
    state["balance_cents"] = state["balance_cents"] + invoice["total_cents"]
    result = {"invoice_id": invoice["invoice_id"], "charged_cents": invoice["total_cents"]}
    state["processed"][key] = result
    return result
'''
_RENEWAL_FIXED = _RENEWAL.replace('key = event["webhook_id"]', 'key = invoice["invoice_id"]')

_WAREHOUSE = '''def apply(state, event):
    change = event["change"]
    key = change["sequence"]
    if key not in state["processed"]:
        sku = change["sku"]
        new_count = state["inventory"][sku] + change["delta"]
        state["inventory"][sku] = new_count
        state["processed"][key] = {"sku": sku, "quantity": new_count}
    return state["processed"][key]
'''
_WAREHOUSE_FIXED = _WAREHOUSE.replace('key = change["sequence"]', 'key = event["warehouse_id"] + ":" + change["sequence"]')

_PARTIAL_REFUND = '''def apply(state, event):
    refund = event["refund"]
    ledger = state["processed"]
    key = refund["order_id"]
    if key in ledger:
        return ledger[key]
    amount = refund["amount_cents"]
    state["refunds"].append({"id": refund["refund_id"], "order_id": refund["order_id"], "amount_cents": amount})
    state["balance_cents"] -= amount
    ledger[key] = {"refund_id": refund["refund_id"], "refunded_cents": amount}
    return ledger[key]
'''
_PARTIAL_REFUND_FIXED = _PARTIAL_REFUND.replace('key = refund["order_id"]', 'key = refund["refund_id"]')

_RELEASE = '''def apply(state, event):
    release = event["release"]
    key = release["cancellation_id"]
    result = {"order_id": release["order_id"], "status": "cancelled"}
    inventory = state["inventory"]
    inventory[release["sku"]] += release["quantity"]
    if key in state["processed"]:
        return state["processed"][key]
    for record in state["orders"]:
        if record["id"] == release["order_id"]:
            record["status"] = "cancelled"
    state["processed"][key] = result
    return result
'''
_RELEASE_FIXED = '''def apply(state, event):
    release = event["release"]
    key = release["cancellation_id"]
    if key in state["processed"]:
        return state["processed"][key]
    inventory = state["inventory"]
    inventory[release["sku"]] += release["quantity"]
    for record in state["orders"]:
        if record["id"] == release["order_id"]:
            record["status"] = "cancelled"
    result = {"order_id": release["order_id"], "status": "cancelled"}
    state["processed"][key] = result
    return result
'''

_HELD_OUT = [
    _case("heldout-renewal", "Subscription invoice charged on redelivery", "Billing", "A renewed subscription receives another webhook envelope for the same invoice.", _RENEWAL, _RENEWAL_FIXED,
          {"webhook_id": "hook-401", "invoice": {"invoice_id": "inv-401", "subscription_id": "sub-4", "total_cents": 2900}},
          {"webhook_id": "hook-403", "invoice": {"invoice_id": "inv-402", "subscription_id": "sub-4", "total_cents": 2900}},
          replay={"webhook_id": "hook-402", "invoice": {"invoice_id": "inv-401", "subscription_id": "sub-4", "total_cents": 2900}},
          family="renewal", keys=("invoice.invoice_id",), nested="invoice", split="eval",
          behavior="A nested invoice.invoice_id identifies one charge. Different webhook_id values may deliver the same invoice. Use the invoice ID as the operation key."),
    _case("heldout-warehouse", "Warehouse sequences collide", "Inventory", "Independent warehouses use overlapping change sequence numbers.", _WAREHOUSE, _WAREHOUSE_FIXED,
          {"warehouse_id": "west", "change": {"sequence": "83", "sku": "widget", "delta": 3}},
          {"warehouse_id": "east", "change": {"sequence": "83", "sku": "widget", "delta": 7}},
          family="delta", keys=("warehouse_id", "change.sequence"), nested="change", split="eval",
          behavior="The operation key is warehouse_id + ':' + change.sequence. Each warehouse's change applies once to the shared inventory count. Return the original result for a replay."),
    _case("heldout-partial-refund", "One order needs two partial refunds", "Refunds", "The first partial refund blocks another legitimate partial refund against the same purchase.", _PARTIAL_REFUND, _PARTIAL_REFUND_FIXED,
          {"refund": {"refund_id": "part-501", "order_id": "purchase-50", "amount_cents": 350}},
          {"refund": {"refund_id": "part-502", "order_id": "purchase-50", "amount_cents": 725}},
          family="refund", keys=("refund.refund_id",), nested="refund", split="eval",
          behavior="Use refund.refund_id as the operation key. One order can have multiple distinct partial refunds. Each individual refund debits the balance once."),
    _case("heldout-fulfillment-release", "Fulfillment retry inflates available stock", "Fulfillment", "A nested stock-release message changes inventory before checking whether it already ran.", _RELEASE, _RELEASE_FIXED,
          {"release": {"cancellation_id": "release-601", "order_id": "ord-601", "sku": "widget", "quantity": 3}},
          {"release": {"cancellation_id": "release-602", "order_id": "ord-602", "sku": "gadget", "quantity": 2}},
          family="cancel", keys=("release.cancellation_id",), nested="release", split="eval",
          initial={**_state(), "orders": [{"id": "ord-601", "status": "paid"}, {"id": "ord-602", "status": "paid"}]},
          behavior="Use release.cancellation_id as the operation key. Apply every cancellation's stock release once, and replay the original JSON response on retries."),
]


def training_cases() -> list[dict[str, Any]]:
    return deepcopy(_TRAIN)


def held_out_cases() -> list[dict[str, Any]]:
    return deepcopy(_HELD_OUT)


def get_case(identifier: str, include_held_out: bool = False) -> dict[str, Any] | None:
    for case in [*_TRAIN, *(_HELD_OUT if include_held_out else [])]:
        if case["id"] == identifier:
            return deepcopy(case)
    return None
