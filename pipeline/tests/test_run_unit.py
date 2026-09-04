from pipeline.models import Product, RejectedRecord, SourceResult
from pipeline.run import _build_summary, _merge_products


def _product(source: str, pid: str) -> Product:
    return Product(id=pid, unified_id=f"{source}:{pid}", title=pid, source=source, price=1.0, category="x")


def test_merge_products_dedups_by_unified_id_last_write_wins():
    r1 = SourceResult(source="source_a", status="success", products=[_product("source_a", "1")])
    r2 = SourceResult(
        source="source_a", status="success",
        products=[_product("source_a", "1"), _product("source_a", "2")],
    )
    products, rejected, duplicates = _merge_products([r1, r2])

    assert duplicates == 1
    assert {p.unified_id for p in products} == {"source_a:1", "source_a:2"}
    assert rejected == []


def test_merge_products_collects_rejected_across_sources():
    bad = RejectedRecord(source="source_b", reason="bad price", raw={})
    r1 = SourceResult(source="source_a", status="success", products=[_product("source_a", "1")])
    r2 = SourceResult(source="source_b", status="success", rejected=[bad])
    _, rejected, _ = _merge_products([r1, r2])
    assert rejected == [bad]


def test_build_summary_status_success_when_all_sources_succeed():
    r1 = SourceResult(source="source_a", status="success", products=[_product("source_a", "1")])
    r2 = SourceResult(source="source_b", status="success", products=[_product("source_b", "1")])
    summary = _build_summary([r1, r2], [_product("source_a", "1"), _product("source_b", "1")], [], 0, "t", 1.0, False)
    assert summary["run"]["status"] == "success"


def test_build_summary_status_partial_success_when_one_source_degraded():
    r1 = SourceResult(source="source_a", status="success", products=[_product("source_a", "1")])
    r2 = SourceResult(source="source_b", status="failed", error="boom")
    summary = _build_summary([r1, r2], [_product("source_a", "1")], [], 0, "t", 1.0, False)
    assert summary["run"]["status"] == "partial_success"
    assert summary["run"]["sources"]["source_b"]["status"] == "failed"
    assert summary["run"]["sources"]["source_b"]["error"] == "boom"


def test_build_summary_status_failure_when_zero_products():
    r1 = SourceResult(source="source_a", status="failed", error="boom")
    r2 = SourceResult(source="source_b", status="failed", error="boom")
    summary = _build_summary([r1, r2], [], [], 0, "t", 1.0, False)
    assert summary["run"]["status"] == "failure"


def test_build_summary_reports_deadline_exceeded():
    r1 = SourceResult(source="source_a", status="success", products=[_product("source_a", "1")])
    summary = _build_summary([r1], [_product("source_a", "1")], [], 0, "t", 1.0, True)
    assert summary["run"]["deadline_exceeded"] is True
