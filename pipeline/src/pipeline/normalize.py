from __future__ import annotations

import math

from pipeline.models import Product

# Types a caller could reasonably mean as an id/title/category. Deliberately
# excludes bool (a stray `true`/`false` is a data error, not a valid label)
# and excludes list/dict (stringifying those hides a malformed record instead
# of rejecting it).
_TEXT_TYPES = (str, int, float)


class RejectRecord(Exception):
    """Raised when a raw record is malformed and must be dropped, not fatal to the page/source."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require_text(value: object, field: str) -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, _TEXT_TYPES):
        raise ValueError(f"{field} is missing or has an unexpected type: {value!r}")
    return str(value)


def _require_price(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"price has an unexpected type: {value!r}")
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"price is not a valid number: {value!r}") from exc
    if not math.isfinite(price):
        raise ValueError(f"price is not a finite number: {value!r}")
    return price


def normalize_source_a(raw: dict) -> Product:
    try:
        raw_id = _require_text(raw["id"], "id")
        title = _require_text(raw["name"], "name")
        price = _require_price(raw["price"])
        category = _require_text(raw["category"], "category")
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectRecord(f"invalid source_a record: {exc}") from exc
    return Product(
        id=raw_id,
        unified_id=f"source_a:{raw_id}",
        title=title,
        source="source_a",
        price=price,
        category=category,
    )


def normalize_source_b(raw: dict) -> Product:
    try:
        raw_id = _require_text(raw["sku"], "sku")
        title = _require_text(raw["title"], "title")
        cents = raw["amount_cents"]
        if not isinstance(cents, (int, float)) or isinstance(cents, bool):
            raise ValueError(f"amount_cents is not numeric: {cents!r}")
        if not math.isfinite(cents):
            raise ValueError(f"amount_cents is not finite: {cents!r}")
        price = round(cents / 100, 2)
        category = _require_text(raw["department"], "department")
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectRecord(f"invalid source_b record: {exc}") from exc
    return Product(
        id=raw_id,
        unified_id=f"source_b:{raw_id}",
        title=title,
        source="source_b",
        price=price,
        category=category,
    )


def normalize_source_c(raw: dict) -> Product:
    try:
        raw_id = _require_text(raw["product_id"], "product_id")
        title = _require_text(raw["product_name"], "product_name")
        price = _require_price(raw["price"])
        category = _require_text(raw["type"], "type")
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectRecord(f"invalid source_c record: {exc}") from exc
    return Product(
        id=raw_id,
        unified_id=f"source_c:{raw_id}",
        title=title,
        source="source_c",
        price=price,
        category=category,
    )
