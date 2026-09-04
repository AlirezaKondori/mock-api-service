from pipeline.models import Product, RejectedRecord, SourceResult


def test_product_fields():
    p = Product(
        id="a-101", unified_id="source_a:a-101", title="Mechanical Keyboard",
        source="source_a", price=89.99, category="electronics",
    )
    assert p.id == "a-101"
    assert p.unified_id == "source_a:a-101"
    assert p.price == 89.99


def test_rejected_record_fields():
    r = RejectedRecord(source="source_b", reason="bad price", raw={"sku": "b-205"})
    assert r.source == "source_b"
    assert r.raw == {"sku": "b-205"}


def test_source_result_defaults_are_independent_instances():
    r1 = SourceResult(source="source_a", status="success")
    r2 = SourceResult(source="source_b", status="success")
    r1.products.append("x")  # type: ignore[arg-type]
    assert r2.products == []  # mutable default must not be shared
