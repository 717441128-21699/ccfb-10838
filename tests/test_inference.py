"""需求 1: 读表/外键 + 未声明外键推断, 且无明显误报."""
from __future__ import annotations

import sqlite3

from submask.inference import infer_foreign_keys
from submask.schema import declared_fks, list_tables, schema_snapshot


def test_schema_reads_30_tables(source_db):
    conn = sqlite3.connect(source_db)
    tables = list_tables(conn)
    assert len(tables) == 30
    snap = schema_snapshot(conn)
    assert set(snap["tables"]) == set(tables)
    # 复合主键能被读出
    assert snap["tables"]["user_roles"]["pk"] == ["user_id", "role_id"]
    conn.close()


def test_declared_foreign_keys_present(source_db):
    conn = sqlite3.connect(source_db)
    fks = declared_fks(conn)
    assert len(fks) >= 20
    # 环形引用: addresses -> customers
    assert any(f.table == "addresses" and f.ref_table == "customers"
               for f in fks)
    conn.close()


def test_inference_finds_undeclared_edges(source_db):
    conn = sqlite3.connect(source_db)
    candidates = infer_foreign_keys(conn)
    keys = {(c.table, c.column, c.ref_table) for c in candidates}

    expected = {
        ("customers", "level_id", "customer_levels"),
        ("customers", "default_address_id", "addresses"),
        ("employees", "manager_id", "employees"),       # 自引用
        ("regions", "parent_id", "regions"),            # 自引用
        ("orders", "parent_order_id", "orders"),        # 自引用
        ("departments", "manager_id", "employees"),     # 部门负责人 -> 员工
        ("point_accounts", "customer_id", "customers"),
        ("login_logs", "user_id", "users"),
        ("audit_logs", "user_id", "users"),
        ("inventory", "warehouse_id", "warehouses"),
        ("customer_services", "order_id", "orders"),
    }
    missing = expected - keys
    assert not missing, f"推断遗漏: {missing}"

    # 所有候选的实际数据包含率必须达到阈值
    assert all(c.containment >= 0.8 for c in candidates)
    # 不应把普通业务列误判为自引用
    assert not any(c.table == "inventory" and c.ref_table == "inventory"
                   for c in candidates)
    conn.close()
