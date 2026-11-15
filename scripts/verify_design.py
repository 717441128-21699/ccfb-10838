"""验收: 源库设计前提 — 30 表、环形引用、未声明外键."""
import sqlite3

from submask.schema import declared_fks
from submask.inference import infer_foreign_keys

conn = sqlite3.connect("data/demo_source.db")

tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' "
    "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
print(f"[设计] 表数量: {len(tables)} (要求 30)")

declared = declared_fks(conn)
decl_pairs = {(f.table, f.column, f.ref_table) for f in declared}
print(f"[设计] 已声明外键: {len(declared)} 条")

# 环形引用 1: customers.default_address_id (未声明) <-> addresses.customer_id (声明)
has_addr_fk = ("addresses", "customer_id", "customers") in decl_pairs
has_default_addr = any(
    c.table == "customers" and c.column == "default_address_id"
    for c in infer_foreign_keys(conn))
print(f"[环形] customers<->addresses: 声明边={has_addr_fk}, "
      f"推断边={has_default_addr}")

# 环形引用 2: 员工/部门环 + 自引用
cands = infer_foreign_keys(conn)
cand_pairs = {(c.table, c.column, c.ref_table) for c in cands}
cycles = {
    "employees.manager_id 自引用": ("employees", "manager_id", "employees"),
    "regions.parent_id 自引用": ("regions", "parent_id", "regions"),
    "orders.parent_order_id 自引用": ("orders", "parent_order_id", "orders"),
    "departments.manager_id -> employees":
        ("departments", "manager_id", "employees"),
}
for label, key in cycles.items():
    print(f"[环形] {label}: {'在' if key in cand_pairs or key in decl_pairs else '缺失'}")

# 未声明外键数量
undeclared = [c for c in cands]
print(f"[设计] 推断出的未声明外键候选: {len(undeclared)} 条")
assert len(tables) == 30
assert has_addr_fk and has_default_addr
assert all(k in cand_pairs or k in decl_pairs for k in cycles.values())
print("\n设计前提全部满足")
