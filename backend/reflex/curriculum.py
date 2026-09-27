"""Deterministic synthetic training variants of six known repair families.

These are 24 curriculum variants, not 24 independent real incidents. No held-out
case is read or used to construct them. Expected results come from transformed
training specifications, not from a model's answer or candidate execution.
"""

from __future__ import annotations

import ast
import hashlib
import random
import re
from copy import deepcopy
from typing import Any

from .repair_cases import training_cases


MAX_CURRICULUM_CASES = 24
_PRODUCTS = (
    ("ceramic-mug", "linen-napkin"),
    ("trail-bottle", "camp-light"),
    ("coffee-bag", "filter-pack"),
    ("notebook", "pencil-set"),
)
_COMMON_ALIASES = (
    {"sku": "product_code", "quantity": "units", "total_cents": "charge_cents", "amount_cents": "refund_cents", "order_id": "purchase_id", "delta": "unit_change"},
    {"sku": "item_code", "quantity": "unit_count", "total_cents": "captured_cents", "amount_cents": "reimbursement_cents", "order_id": "sale_id", "delta": "change_units"},
    {"sku": "catalog_code", "quantity": "item_count", "total_cents": "paid_cents", "amount_cents": "credit_cents", "order_id": "transaction_id", "delta": "stock_change"},
    {"sku": "stock_code", "quantity": "reserved_units", "total_cents": "payment_cents", "amount_cents": "returned_cents", "order_id": "checkout_id", "delta": "quantity_change"},
)
_IDENTITY_ALIASES = {
    "repair-order-replay": (
        {"event_id": "checkout_event_id"}, {"event_id": "payment_receipt_id"},
        {"event_id": "order_paid_event_id"}, {"event_id": "completion_id"},
    ),
    "repair-stock-replay": (
        {"update_id": "movement_id"}, {"update_id": "adjustment_event_id"},
        {"update_id": "ledger_entry_id"}, {"update_id": "stock_event_id"},
    ),
    "repair-refund-retry": (
        {"delivery_id": "transport_id", "refund_id": "reimbursement_id"},
        {"delivery_id": "attempt_id", "refund_id": "refund_operation_id"},
        {"delivery_id": "envelope_id", "refund_id": "credit_operation_id"},
        {"delivery_id": "notification_id", "refund_id": "return_payment_id"},
    ),
    "repair-tenant-checkout": (
        {"tenant_id": "merchant_id", "request_id": "checkout_request_id"},
        {"tenant_id": "shop_id", "request_id": "client_request_id"},
        {"tenant_id": "account_id", "request_id": "payment_request_id"},
        {"tenant_id": "store_id", "request_id": "operation_request_id"},
    ),
    "repair-stock-overdedupe": (
        {"adjustment_id": "movement_id"}, {"adjustment_id": "stock_entry_id"},
        {"adjustment_id": "correction_id"}, {"adjustment_id": "inventory_operation_id"},
    ),
    "repair-cancel-replay": (
        {"cancellation_id": "release_id"}, {"cancellation_id": "void_operation_id"},
        {"cancellation_id": "reservation_release_id"}, {"cancellation_id": "cancel_operation_id"},
    ),
}


class _EventSchemaAliases(ast.NodeTransformer):
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "event" and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            node.slice = ast.copy_location(ast.Constant(self.aliases.get(node.slice.value, node.slice.value)), node.slice)
        return node


def _source_with_aliases(source: str, aliases: dict[str, str]) -> str:
    tree = _EventSchemaAliases(aliases).visit(ast.parse(source))
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def _identifiers(case: dict[str, Any], suffix: str, products: tuple[str, str]) -> dict[str, str]:
    result = {"widget": products[0], "gadget": products[1]}
    for check in case["_checks"]:
        for event in check["events"]:
            for key, value in event.items():
                if key.endswith("_id") and isinstance(value, str):
                    result[value] = value + "-" + suffix
    return result


def _replace_identifier(value: str, identifiers: dict[str, str]) -> str:
    if value in identifiers:
        return identifiers[value]
    # Compound tenant/request ledger keys retain their original scope relation.
    if ":" in value:
        return ":".join(identifiers.get(part, part) for part in value.split(":"))
    return value


def _scenario_values(value: Any, identifiers: dict[str, str], quantity_scale: int, money_scale: int, field: str = "") -> Any:
    if isinstance(value, dict):
        if field == "inventory":
            return {_replace_identifier(str(key), identifiers): count * quantity_scale for key, count in value.items()}
        return {
            _replace_identifier(str(key), identifiers): _scenario_values(item, identifiers, quantity_scale, money_scale, str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scenario_values(item, identifiers, quantity_scale, money_scale, field) for item in value]
    if isinstance(value, str):
        return _replace_identifier(value, identifiers)
    if isinstance(value, int) and not isinstance(value, bool):
        if field in {"quantity", "delta"}:
            return value * quantity_scale
        if field.endswith("_cents"):
            return value * money_scale
    return value


def _payload(event: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    return {aliases.get(key, key): value for key, value in event.items()}


def _make_variant(template: dict[str, Any], variant: int, seed: int, rng: random.Random) -> dict[str, Any]:
    aliases = {**_COMMON_ALIASES[variant], **_IDENTITY_ALIASES[template["id"]][variant]}
    family = template["id"].removeprefix("repair-")
    suffix = f"{family}-v{variant + 1}-s{seed}"
    quantity_scale = rng.randint(1, 3)
    money_scale = rng.randint(1, 5)
    products = _PRODUCTS[rng.randrange(len(_PRODUCTS))]
    identifiers = _identifiers(template, suffix, products)
    case = _scenario_values(deepcopy(template), identifiers, quantity_scale, money_scale)
    case["id"] = "generated-" + suffix
    case["title"] = f"{template['title']} · generated variant {variant + 1}"
    case["description"] = (
        f"Generated synthetic training variant {variant + 1} of the {family} family. "
        "Event-field names, product identifiers, operation IDs, and scenario quantities vary "
        "from one known training template; this is not an independent production incident."
    )
    case["source_kind"] = "generated"
    case["_split"] = "train"
    case["source"] = _source_with_aliases(template["source"], aliases)
    case["_reference_code"] = _source_with_aliases(template["_reference_code"], aliases)
    for action in case["actions"]:
        action["payload"] = _payload(action["payload"], aliases)
    case["reproduction"] = [_payload(event, aliases) for event in case["reproduction"]]
    for check in case["_checks"]:
        check["events"] = [_payload(event, aliases) for event in check["events"]]
    behavior = template["expected_behavior"]
    for original, replacement in sorted(aliases.items(), key=lambda pair: -len(pair[0])):
        behavior = re.sub(r"\b" + re.escape(original) + r"\b", replacement, behavior)
    # Returned JSON field names stay unchanged even when event input names vary.
    case["expected_behavior"] = behavior + " Only the incoming event schema is renamed; preserve the existing handler's response field names."
    case["_generation"] = {
        "kind": "synthetic_training_variant", "template_case_id": template["id"],
        "family": family, "variant": variant + 1, "seed": seed,
        "quantity_scale": quantity_scale, "money_scale": money_scale,
        "event_field_aliases": aliases,
        "source_ast_hash": hashlib.sha256(ast.dump(ast.parse(case["source"]), include_attributes=False).encode()).hexdigest(),
    }
    return case


def generate_curriculum(count: int = 24, seed: int = 42) -> list[dict[str, Any]]:
    """Return 1–24 deterministic training-only variants, interleaving families.

    Prefix stability lets a six-case run grow to 24 without changing its first
    cases. Every group of six adds one variant from each original family.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_CURRICULUM_CASES:
        raise ValueError("count must be an integer between 1 and 24")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 4_294_967_295:
        raise ValueError("seed must be an integer between 0 and 4294967295")
    templates = training_cases()
    if len(templates) != 6 or {case["id"] for case in templates} != set(_IDENTITY_ALIASES):
        raise ValueError("The synthetic curriculum requires the six versioned training templates")
    rng = random.Random(seed)
    result = []
    for variant in range(4):
        for template in templates:
            result.append(_make_variant(template, variant, seed, rng))
            if len(result) == count:
                return result
    return result
