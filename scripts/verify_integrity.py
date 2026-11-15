"""独立第三方验收: 不调用 submask.validator, 直接对目标库做全量检查."""
import sqlite3

SRC = "data/demo_source.db"
DST = "data/demo_target.db"
src = sqlite3.connect(SRC)
dst = sqlite3.connect(DST)

print("=" * 60)
print("需求3 专项: 大表比例抽样 + 目标库外键零断裂 (独立核验)")
print("=" * 60)

# 1. 比例抽样确实缩减了行数
print("\n[1] 大表抽样比例核验 (源 -> 目标):")
for t, expect in [("order_items", 60), ("login_logs", 40),
                  ("audit_logs", 50), ("messages", 50),
                  ("product_reviews", 60)]:
    s = src.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    d = dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    ratio = round(100 * d / s, 1)
    # 可达行可能少于全表, 目标行数应不超过源行数且确有缩减
    print(f"  {t:18s} {s:6d} -> {d:6d}  ({ratio}% of source, 配置 {expect}%)")
    assert d < s, f"{t} 未缩减"

# 2. 目标库内部: 对每条外键关系, 子表外键值必须都能在父表找到
print("\n[2] 目标库全量外键完整性 (逐边独立 JOIN 检查):")
# 从源库读全部声明外键 + 用推断补未声明的
from submask.schema import declared_fks
from submask.inference import infer_foreign_keys
edges = [(f.table, f.column, f.ref_table, f.ref_column)
         for f in declared_fks(src)]
for c in infer_foreign_keys(src):
    edges.append((c.table, c.column, c.ref_table, c.ref_column))

total_orphans = 0
for child, col, parent, pcol in edges:
    # 目标库里该子表/列是否存在
    exists = dst.execute(
        "SELECT 1 FROM pragma_table_info(?) WHERE name=?", (child, col)).fetchone()
    if not exists:
        continue
    orphans = dst.execute(
        f'SELECT COUNT(*) FROM "{child}" c WHERE c."{col}" IS NOT NULL '
        f'AND NOT EXISTS (SELECT 1 FROM "{parent}" p '
        f'WHERE p."{pcol}" = c."{col}")').fetchone()[0]
    flag = "OK" if orphans == 0 else f"断裂{orphans}"
    print(f"  {child}.{col} -> {parent}.{pcol}: {flag}")
    total_orphans += orphans

print(f"\n悬空外键总数: {total_orphans} (要求 0)")
assert total_orphans == 0

# 3. 引用完整性正向: 目标库每个非空外键值在父表都有对应主键行
print("\n[3] 父表覆盖核验: 抽样子表引用的父行一条不落")
# order_items 被抽到 60%, 它引用的 orders/products 必须完整覆盖
for child, col, parent, pcol in [
        ("order_items", "order_id", "orders", "id"),
        ("order_items", "product_id", "products", "id"),
        ("login_logs", "user_id", "users", "id")]:
    missing = dst.execute(
        f'SELECT COUNT(DISTINCT c."{col}") FROM "{child}" c '
        f'WHERE c."{col}" IS NOT NULL AND NOT EXISTS '
        f'(SELECT 1 FROM "{parent}" p WHERE p."{pcol}"=c."{col}")').fetchone()[0]
    print(f"  {child}.{col} 引用的 {parent} 缺失: {missing}")
    assert missing == 0

print("\n" + "=" * 60)
print("需求3 独立验收通过: 抽样有效, 外键零断裂, 引用父行完整")
print("=" * 60)
src.close()
dst.close()
