"""需求 2/3: 种子闭包、引用一条不落、比例抽样、环形引用收敛."""
from __future__ import annotations

import sqlite3

from submask.extraction import Extractor, TableRule
from submask.graph import RelationshipGraph
from submask.inference import infer_foreign_keys
from submask.schema import ForeignKey, declared_fks


def build_graph(conn):
    declared = declared_fks(conn)
    inferred = infer_foreign_keys(conn)
    confirmed = [ForeignKey(table=c.table, column=c.column,
                            ref_table=c.ref_table, ref_column=c.ref_column)
                 for c in inferred]
    return RelationshipGraph.build(declared, confirmed)


def test_seed_closure_brings_orders_items_addresses(source_db):
    conn = sqlite3.connect(source_db)
    graph = build_graph(conn)
    rules = {"customers": TableRule(
        mode="seed", where="level_id >= 4 AND status='active'")}
    result = Extractor(conn, graph, rules).run()

    # 种子客户被选中
    seed_ids = set(result.seed_selected["customers"])
    assert seed_ids and seed_ids.issubset(set(result.selected["customers"]))
    # 顺关系带出的核心实体都在
    for t in ("orders", "order_items", "addresses", "payments", "shipments"):
        assert result.table_count(t) > 0, f"{t} 未被闭包带出"
    conn.close()


def test_no_dangling_reference_after_percent_sampling(source_db):
    """大表抽样后, 它引用的父行必须被补齐 (外键不断)."""
    conn = sqlite3.connect(source_db)
    graph = build_graph(conn)
    rules = {
        "customers": TableRule(mode="seed", where="level_id >= 3"),
        "order_items": TableRule(mode="percent", percent=30),
        "login_logs": TableRule(mode="percent", percent=25),
        "audit_logs": TableRule(mode="percent", percent=40),
    }
    result = Extractor(conn, graph, rules).run()

    # 对每条边, 子集内子表外键值必须全部存在于子集父表 PK 中
    def chunks(seq, size=800):
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    for edge in graph.edges:
        child_ids = result.selected.get(edge.table)
        if not child_ids:
            continue
        parent_ids = set(result.selected.get(edge.ref_table, []))
        fk_values = set()
        for chunk in chunks(child_ids):
            ph = ",".join("?" for _ in chunk)
            fk_values.update(r[0] for r in conn.execute(
                f'SELECT DISTINCT "{edge.column}" FROM "{edge.table}" '
                f'WHERE rowid IN ({ph}) AND "{edge.column}" IS NOT NULL',
                chunk).fetchall())
        parent_pks = set()
        for chunk in chunks(list(parent_ids)):
            ph = ",".join("?" for _ in chunk)
            parent_pks.update(r[0] for r in conn.execute(
                f'SELECT "{edge.ref_column}" FROM "{edge.ref_table}" '
                f'WHERE rowid IN ({ph})', chunk).fetchall())
        orphans = fk_values - parent_pks
        assert not orphans, (
            f"{edge.table}.{edge.column} 存在悬空引用 {list(orphans)[:3]}")
    conn.close()


def test_percent_sampling_is_deterministic_and_reduced(source_db):
    conn = sqlite3.connect(source_db)
    graph = build_graph(conn)
    rules = {"customers": TableRule(mode="seed", where="1=1"),
             "order_items": TableRule(mode="percent", percent=50)}
    r1 = Extractor(conn, graph, rules).run()
    r2 = Extractor(conn, graph, rules).run()
    assert r1.selected["order_items"] == r2.selected["order_items"]
    total = conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
    assert len(r1.selected["order_items"]) < total
    conn.close()


def test_percent_ratio_applies_to_reachable_rows(source_db):
    """比例抽样作用在闭包可达行上: 无其他表回引时, 结果应接近配置比例."""
    conn = sqlite3.connect(source_db)
    graph = build_graph(conn)
    # login_logs 只被 users 单向引用, 没有别的表回引它, 比例应精确
    rules = {"customers": TableRule(mode="seed", where="1=1"),
             "login_logs": TableRule(mode="percent", percent=33)}
    result = Extractor(conn, graph, rules).run()
    total = conn.execute("SELECT COUNT(*) FROM login_logs").fetchone()[0]
    kept = result.table_count("login_logs")
    # 全部 users 可达 -> 全部 login_logs 可达, 抽样 33%
    assert abs(kept - round(total * 0.33)) <= 1, (kept, total)
    conn.close()


def test_cyclic_graph_converges(source_db):
    conn = sqlite3.connect(source_db)
    graph = build_graph(conn)
    rules = {"customers": TableRule(mode="seed", where="id <= 20")}
    result = Extractor(conn, graph, rules).run()
    # 环上的表都到达且数量有限 (固定点收敛, 不会无限增长)
    assert 0 < result.table_count("addresses") <= 975
    assert result.table_count("customers") >= 20
    conn.close()


def test_seed_snapshot_not_polluted_by_closure(source_db):
    """种子快照必须只含 WHERE 命中行, 不被向下闭包反向带回的行污染."""
    conn = sqlite3.connect(source_db)
    graph = build_graph(conn)
    rules = {"customers": TableRule(mode="seed", where="level_id = 5")}
    result = Extractor(conn, graph, rules).run()

    seed_n = len(result.seed_selected["customers"])
    direct = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE level_id = 5").fetchone()[0]
    assert seed_n == direct                       # 快照 == WHERE 命中数
    assert result.table_count("customers") > seed_n   # 闭包确实带回了更多
    # 快照里每一行都满足种子条件
    rowids = result.seed_selected["customers"]
    bad = conn.execute(
        f"SELECT COUNT(*) FROM customers WHERE rowid IN "
        f"({','.join('?' for _ in rowids)}) AND level_id <> 5",
        rowids).fetchone()[0] if rowids else 0
    assert bad == 0
    conn.close()
