import pytest

from pipeline.normalize import (
    RejectRecord,
    normalize_source_a,
    normalize_source_b,
    normalize_source_c,
)


def test_normalize_source_a_happy_path():
    raw = {"id": "a-101", "name": "Mechanical Keyboard", "price": 89.99, "category": "electronics"}
    product = normalize_source_a(raw)
    assert product.id == "a-101"
    assert product.unified_id == "source_a:a-101"
    assert product.title == "Mechanical Keyboard"
    assert product.source == "source_a"
    assert product.price == 89.99
    assert product.category == "electronics"


def test_normalize_source_a_missing_field_is_rejected():
    raw = {"id": "a-101", "name": "Mechanical Keyboard", "category": "electronics"}
    with pytest.raises(RejectRecord):
        normalize_source_a(raw)


def test_normalize_source_b_converts_cents_to_dollars():
    raw = {"sku": "b-201", "title": "Desk Lamp", "amount_cents": 3499, "department": "home"}
    product = normalize_source_b(raw)
    assert product.price == 34.99
    assert product.unified_id == "source_b:b-201"
    assert product.category == "home"


def test_normalize_source_b_rejects_non_numeric_price():
    raw = {"sku": "b-205", "title": "Broken Price Example", "amount_cents": "not-a-number", "department": "home"}
    with pytest.raises(RejectRecord):
        normalize_source_b(raw)


def test_normalize_source_b_rejects_none_price():
    raw = {"sku": "b-201", "title": "Desk Lamp", "amount_cents": None, "department": "home"}
    with pytest.raises(RejectRecord):
        normalize_source_b(raw)


def test_normalize_source_b_rejects_missing_department():
    raw = {"sku": "b-201", "title": "Desk Lamp", "amount_cents": 3499}
    with pytest.raises(RejectRecord):
        normalize_source_b(raw)


def test_normalize_source_c_converts_string_price_to_float():
    raw = {"product_id": "c-301", "product_name": "USB-C Hub", "price": "49.50", "type": "electronics"}
    product = normalize_source_c(raw)
    assert product.price == 49.5
    assert product.unified_id == "source_c:c-301"


def test_normalize_source_c_rejects_missing_field():
    raw = {"product_id": "c-301", "product_name": "USB-C Hub", "type": "electronics"}
    with pytest.raises(RejectRecord):
        normalize_source_c(raw)
