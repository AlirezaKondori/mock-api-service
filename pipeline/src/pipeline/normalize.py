from __future__ import annotations

from pipeline.models import Product


class RejectRecord(Exception):
    """Raised when a raw record is malformed and must be dropped, not fatal to the page/source."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_source_a(raw: dict) -> Product:
    try:
        raw_id = raw["id"]
        title = raw["name"]
        price = float(raw["price"])
        category = raw["category"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectRecord(f"invalid source_a record: {exc}") from exc
    return Product(
        id=str(raw_id),
        unified_id=f"source_a:{raw_id}",
        title=str(title),
        source="source_a",
        price=price,
        category=str(category),
    )


def normalize_source_b(raw: dict) -> Product:
    try:
        raw_id = raw["sku"]
        title = raw["title"]
        cents = raw["amount_cents"]
        if not isinstance(cents, (int, float)) or isinstance(cents, bool):
            raise ValueError(f"amount_cents is not numeric: {cents!r}")
        price = round(cents / 100, 2)
        category = raw["department"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectRecord(f"invalid source_b record: {exc}") from exc
    return Product(
        id=str(raw_id),
        unified_id=f"source_b:{raw_id}",
        title=str(title),
        source="source_b",
        price=price,
        category=str(category),
    )


def normalize_source_c(raw: dict) -> Product:
    try:
        raw_id = raw["product_id"]
        title = raw["product_name"]
        price = float(raw["price"])
        category = raw["type"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RejectRecord(f"invalid source_c record: {exc}") from exc
    return Product(
        id=str(raw_id),
        unified_id=f"source_c:{raw_id}",
        title=str(title),
        source="source_c",
        price=price,
        category=str(category),
    )
