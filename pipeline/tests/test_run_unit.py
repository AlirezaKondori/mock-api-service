from pathlib import Path

from pipeline.models import Product, RejectedRecord, SourceResult
from pipeline.run import _build_summary, _merge_products, write_output


def _product(source: str, pid: str) -> Product:
    return Product(id=pid, unified_id=f"{source}:{pid}", title=pid, source=source, price=1.0, category="x")


def test_merge_products_dedups_by_unified_id_last_write_wins():
    # Using two genuinely different payloads for the same unified_id (rather
    # than two identical copies) is the only way this test can distinguish
    # "last write wins" from "first write wins" or "arbitrary write wins" —
    # identical duplicates pass under any of those merge policies.
    older = Product(id="1", unified_id="source_a:1", title="Old Title", source="source_a", price=1.0, category="x")
    newer = Product(id="1", unified_id="source_a:1", title="New Title", source="source_a", price=2.0, category="x")
    r1 = SourceResult(source="source_a", status="success", products=[older])
    r2 = SourceResult(
        source="source_a", status="success",
        products=[newer, _product("source_a", "2")],
    )
    products, rejected, duplicates = _merge_products([r1, r2])

    assert duplicates == 1
    by_id = {p.unified_id: p for p in products}
    assert by_id.keys() == {"source_a:1", "source_a:2"}
    assert by_id["source_a:1"].title == "New Title"
    assert by_id["source_a:1"].price == 2.0
    assert rejected == []


def test_merge_products_keeps_matching_raw_ids_distinct_across_sources():
    # Same raw id from two different sources must not collide — unified_id
    # namespaces by source, so "1" from source_a and "1" from source_b are
    # different products, not duplicates.
    r1 = SourceResult(source="source_a", status="success", products=[_product("source_a", "1")])
    r2 = SourceResult(source="source_b", status="success", products=[_product("source_b", "1")])
    products, rejected, duplicates = _merge_products([r1, r2])

    assert duplicates == 0
    assert {p.unified_id for p in products} == {"source_a:1", "source_b:1"}


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


def test_write_output_does_not_collide_on_two_runs_in_the_same_second(tmp_path: Path):
    # Filenames used to be timestamp-only (second precision), so two runs
    # completing within the same second would silently overwrite one another.
    path1 = write_output({"run": {"status": "success"}}, tmp_path)
    path2 = write_output({"run": {"status": "failure"}}, tmp_path)

    assert path1 != path2
    assert path1.exists()
    assert path2.exists()
