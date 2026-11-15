"""End-to-end demo / acceptance driver (no web needed).

流程: 读 schema -> 推断未声明外键 -> 全部确认 -> 配置种子/比例/脱敏 ->
闭包抽取 -> 建目标库并脱敏 -> 外键检查 + 格式校验 -> 打印报告.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from submask.extraction import Extractor, TableRule
from submask.graph import RelationshipGraph
from submask.inference import infer_foreign_keys
from submask.masking import MaskingEngine
from submask.report import build_report
from submask.schema import ForeignKey, declared_fks
from submask.state import utcnow
from submask.target_builder import create_target, load_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "demo_source.db")
DST = os.path.join(ROOT, "data", "demo_target.db")
STATE = os.path.join(ROOT, "data", "demo_state.db")
REPORT = os.path.join(ROOT, "data", "demo_report.json")

# 大表按比例抽 (从可达行中等距抽样, 父行仍被闭包补齐)
PERCENT_TABLES = {"order_items": 60, "login_logs": 40, "audit_logs": 50,
                  "messages": 50, "product_reviews": 60}

# 敏感列 -> 脱敏策略
MASKING = {
    "customers": {"name": "name", "phone": "phone", "id_card": "id_card",
                  "bank_card": "bank_card", "email": "email"},
    "employees": {"name": "name", "phone": "phone", "id_card": "id_card",
                  "bank_card": "bank_card"},
    "addresses": {"receiver": "name", "phone": "phone"},
}
DATE_SHIFT_DAYS = 180


def main() -> int:
    for p in (DST, STATE, REPORT):
        if os.path.exists(p):
            os.remove(p)

    src = sqlite3.connect(SRC)
    started = utcnow()

    # 1. 声明外键 + 推断外键 (演示中全部确认; Web 上由用户勾选)
    declared = declared_fks(src)
    inferred = infer_foreign_keys(src)
    confirmed = [ForeignKey(table=c.table, column=c.column,
                            ref_table=c.ref_table, ref_column=c.ref_column)
                 for c in inferred]
    graph = RelationshipGraph.build(declared, confirmed)
    print(f"[1] 声明外键 {len(declared)} 条, 推断并确认 {len(confirmed)} 条, "
          f"关系图共 {len(graph.edges)} 条边")

    # 2. 规则: 金卡/铂金/钻石客户为种子; 大表按比例
    rules = {"customers": TableRule(mode="seed",
                                    where="level_id >= 3 AND status='active'")}
    for t, pct in PERCENT_TABLES.items():
        rules[t] = TableRule(mode="percent", percent=pct)

    result = Extractor(src, graph, rules).run()
    print(f"[2] 种子客户闭包完成, 涉及 {len(result.selected)} 张表")
    for t in sorted(result.selected):
        print(f"      {t:22s} {len(result.selected[t]):>7d} 行")

    # 3. 建目标库 + 脱敏写入
    dst = create_target(src, DST, graph, list(result.selected))
    state = sqlite3.connect(STATE)
    engine = MaskingEngine(state, salt="submask-v1")
    counts = load_data(src, dst, graph, result.selected, MASKING,
                       engine, DATE_SHIFT_DAYS)
    print(f"[3] 目标库已写入 {sum(counts.values())} 行 (脱敏 salt 固定, "
          f"日期整体平移 {DATE_SHIFT_DAYS} 天)")

    # 4. 校验 + 报告
    finished = utcnow()
    report = build_report(
        "demo-e2e", src, dst, source_db=SRC, target_db=DST,
        started_at=started, finished_at=finished, status="success",
        extraction_result=result, load_counts=counts, masking_cfg=MASKING,
        engine=engine, date_shift_days=DATE_SHIFT_DAYS)
    report.save(REPORT)

    v = report.validation
    print("[4] 校验结果:")
    print(f"      外键错误: {v['foreign_key_errors']}")
    print(f"      格式错误: {v['format_errors']}")
    print(f"      零错误:   {v['zero_error']}")

    # 5. 额外断言: 目标库重复跑一次, 脱敏值必须完全一致
    first_db = sqlite3.connect(DST)
    row_a = first_db.execute(
        "SELECT name, phone, id_card FROM customers ORDER BY id LIMIT 5").fetchall()
    first_db.close()
    dst.close()
    os.remove(DST)
    state2 = sqlite3.connect(STATE)          # 复用同一持久化映射
    engine2 = MaskingEngine(state2, salt="submask-v1")
    dst2 = create_target(src, DST, graph, list(result.selected))
    load_data(src, dst2, graph, result.selected, MASKING, engine2,
              DATE_SHIFT_DAYS)
    row_b = dst2.execute(
        "SELECT name, phone, id_card FROM customers ORDER BY id LIMIT 5").fetchall()
    assert row_a == row_b, "二次作业脱敏值不一致"
    print("[5] 二次作业脱敏值完全一致 (确定性验证通过)")

    src.close()
    dst2.close()
    state.close()
    state2.close()
    print(f"\n报告: {REPORT}")
    print(f"目标库: {DST}")
    return 0 if v["zero_error"] else 1


if __name__ == "__main__":
    sys.exit(main())
