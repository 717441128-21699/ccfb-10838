"""需求 7 + 总验收: 完整流水线, 目标库外键检查与格式校验零错误."""
from __future__ import annotations

import json
import sqlite3

from submask.extraction import Extractor, TableRule
from submask.graph import RelationshipGraph
from submask.inference import infer_foreign_keys
from submask.masking import MaskingEngine
from submask.report import build_report
from submask.schema import ForeignKey, declared_fks
from submask.target_builder import create_target, load_data
from submask.validator import foreign_key_violations, format_violations

MASKING = {
    "customers": {"name": "name", "phone": "phone", "id_card": "id_card",
                  "bank_card": "bank_card", "email": "email"},
    "employees": {"name": "name", "phone": "phone", "id_card": "id_card",
                  "bank_card": "bank_card"},
    "addresses": {"receiver": "name", "phone": "phone"},
}
RULES = {
    "customers": TableRule(mode="seed",
                           where="level_id >= 3 AND status='active'"),
    "order_items": TableRule(mode="percent", percent=60),
    "login_logs": TableRule(mode="percent", percent=40),
    "audit_logs": TableRule(mode="percent", percent=50),
    "messages": TableRule(mode="percent", percent=50),
    "product_reviews": TableRule(mode="percent", percent=60),
}
SHIFT = 180


def _pipeline(source_db, target_db, state_db):
    src = sqlite3.connect(source_db)
    declared = declared_fks(src)
    confirmed = [ForeignKey(table=c.table, column=c.column,
                            ref_table=c.ref_table, ref_column=c.ref_column)
                 for c in infer_foreign_keys(src)]
    graph = RelationshipGraph.build(declared, confirmed)
    result = Extractor(src, graph, RULES).run()
    dst = create_target(src, target_db, graph, list(result.selected))
    engine = MaskingEngine(sqlite3.connect(state_db), salt="acceptance")
    counts = load_data(src, dst, graph, result.selected, MASKING, engine, SHIFT)
    return src, dst, engine, result, counts, graph


def test_target_has_zero_foreign_key_and_format_errors(
        source_db, tmp_target, tmp_state):
    src, dst, engine, result, counts, graph = _pipeline(
        source_db, tmp_target, tmp_state)

    assert not foreign_key_violations(dst), "目标库存在外键违约"
    assert not format_violations(dst, MASKING), "目标库存在格式非法的脱敏值"

    # 报告可生成且记录零错误
    from submask.state import utcnow
    report = build_report("t1", src, dst, source_db=source_db,
                          target_db=tmp_target, started_at=utcnow(),
                          finished_at=utcnow(), status="success",
                          extraction_result=result, load_counts=counts,
                          masking_cfg=MASKING, engine=engine,
                          date_shift_days=SHIFT)
    assert report.validation["zero_error"] is True
    # 每张被抽取的表在报告里都有行
    assert all(t["extracted_rows"] >= 0 for t in report.tables)
    assert len(report.tables) == 30
    src.close()
    dst.close()


def test_rerun_produces_identical_masked_values(
        source_db, tmp_path, tmp_state):
    t1 = str(tmp_path / "a.db")
    t2 = str(tmp_path / "b.db")
    src, dst1, eng1, *_ = _pipeline(source_db, t1, tmp_state)
    dst1.close()
    _, dst2, eng2, *_ = _pipeline(source_db, t2, tmp_state)

    c1 = sqlite3.connect(t1)
    rows1 = c1.execute(
        "SELECT name, phone, id_card, bank_card FROM customers "
        "ORDER BY id").fetchall()
    rows2 = dst2.execute(
        "SELECT name, phone, id_card, bank_card FROM customers "
        "ORDER BY id").fetchall()
    assert rows1 == rows2
    # 源值与假值不同
    src_rows = src.execute(
        "SELECT name, phone FROM customers ORDER BY id LIMIT 50").fetchall()
    fake_rows = rows2[:50]
    assert all(s[0] != f[0] and s[1] != f[1]
               for s, f in zip(src_rows, fake_rows))
    c1.close()
    dst2.close()
    src.close()


def test_dates_are_shifted_and_order_preserved(source_db, tmp_target, tmp_state):
    src, dst, *_ = _pipeline(source_db, tmp_target, tmp_state)
    before, after = dst.execute(
        "SELECT (SELECT MIN(created_at) FROM orders), "
        "(SELECT MAX(created_at) FROM orders)").fetchone()
    src_min, src_max = src.execute(
        "SELECT MIN(created_at), MAX(created_at) FROM orders").fetchone()
    from datetime import datetime
    fmt = "%Y-%m-%d %H:%M:%S"
    delta = datetime.strptime(before, fmt) - datetime.strptime(src_min, fmt)
    assert delta.days == SHIFT
    delta_max = datetime.strptime(after, fmt) - datetime.strptime(src_max, fmt)
    assert delta_max.days == SHIFT
    src.close()
    dst.close()


def test_report_file_roundtrip(source_db, tmp_target, tmp_state, tmp_path):
    src, dst, engine, result, counts, _ = _pipeline(
        source_db, tmp_target, tmp_state)
    from submask.state import utcnow
    report = build_report("t2", src, dst, source_db=source_db,
                          target_db=tmp_target, started_at=utcnow(),
                          finished_at=utcnow(), status="success",
                          extraction_result=result, load_counts=counts,
                          masking_cfg=MASKING, engine=engine,
                          date_shift_days=SHIFT)
    path = tmp_path / "report.json"
    report.save(str(path))
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["validation"]["zero_error"] is True
    assert {m["strategy"] for col in loaded["masking"].values()
            for m in col.values()} <= set(MaskingEngine.STRATEGIES)
    src.close()
    dst.close()
