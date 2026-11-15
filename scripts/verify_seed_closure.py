"""验证窄种子条件下的闭包扩散与种子/闭包拆分 (需求2)."""
import sqlite3

from submask.extraction import Extractor, TableRule
from submask.graph import RelationshipGraph
from submask.inference import infer_foreign_keys
from submask.schema import declared_fks, ForeignKey

conn = sqlite3.connect("data/demo_source.db")
declared = declared_fks(conn)
confirmed = [ForeignKey(table=c.table, column=c.column,
                        ref_table=c.ref_table, ref_column=c.ref_column)
             for c in infer_foreign_keys(conn)]
graph = RelationshipGraph.build(declared, confirmed)

# 窄种子: 只选钻石客户 (level_id=5)
rule = {"customers": TableRule(mode="seed", where="level_id = 5")}
result = Extractor(conn, graph, rule).run()

# seed_selected 是种子直选; selected 是闭包后的最终集
seed_n = len(result.seed_selected["customers"])
total_n = result.table_count("customers")
print(f"钻石客户种子直选: {seed_n} 行")
print(f"闭包后 customers 总数: {total_n} 行 (其余由订单等关系反向带回)")
assert 0 < seed_n < total_n, "闭包没有把关联客户带回来"

# 顺关系带出的核心实体
for t in ("orders", "order_items", "addresses", "payments", "shipments",
          "products", "employees"):
    print(f"  {t:<16} {result.table_count(t):>6} 行")
    assert result.table_count(t) > 0

# 环形: 每个保留客户的 default_address_id 指向的地址必须在子集内
addr_ids = set(result.selected.get("addresses", []))
broken = 0
for cid in result.selected["customers"]:
    da = conn.execute(
        "SELECT default_address_id FROM customers WHERE rowid=?",
        (cid,)).fetchone()[0]
    if da is None:
        continue
    addr_rowid = conn.execute(
        "SELECT rowid FROM addresses WHERE id=?", (da,)).fetchone()
    if not addr_rowid or addr_rowid[0] not in addr_ids:
        broken += 1
print(f"\n环形引用 (客户->默认地址) 断裂数: {broken}")
assert broken == 0
print("\n窄种子闭包扩散与环形完整性验证通过")
conn.close()
