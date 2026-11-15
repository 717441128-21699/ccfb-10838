"""证明需求 5: 同一原值在所有表里脱成同一个假值 (按行 ID 关联源/目标)."""
import sqlite3

src = sqlite3.connect("data/demo_source.db")
dst = sqlite3.connect("data/demo_target.db")

# 1. 手机号: 源库中 customers.phone 与 addresses.phone 相同的行对
pairs = src.execute("""
    SELECT c.id, a.id, c.phone
    FROM customers c JOIN addresses a ON a.phone = c.phone
""").fetchall()
print(f"源库中跨表手机号相同的行对: {len(pairs)} 组")
assert pairs, "演练库无跨表同值样本"

bad = 0
for cid, aid, orig in pairs:
    cf = dst.execute("SELECT phone FROM customers WHERE id=?", (cid,)).fetchone()[0]
    af = dst.execute("SELECT phone FROM addresses WHERE id=?", (aid,)).fetchone()[0]
    if cf != af:
        bad += 1
        print(f"  不一致! 原值 {orig} -> {cf} / {af}")
print(f"手机号跨表不一致数: {bad}")

# 2. 姓名: customers.name 与 addresses.receiver
name_pairs = src.execute("""
    SELECT c.id, a.id, c.name FROM customers c
    JOIN addresses a ON a.receiver = c.name
""").fetchall()
print(f"源库中跨表姓名相同的行对: {len(name_pairs)} 组")
name_bad = 0
for cid, aid, orig in name_pairs:
    cn = dst.execute("SELECT name FROM customers WHERE id=?", (cid,)).fetchone()[0]
    an = dst.execute("SELECT receiver FROM addresses WHERE id=?", (aid,)).fetchone()[0]
    if cn != an:
        name_bad += 1
print(f"姓名跨表不一致数: {name_bad}")

# 3. 身份证: 同一原值在 customers / employees 两表 (构造交集验证)
id_intersection = src.execute("""
    SELECT c.id, e.id, c.id_card FROM customers c
    JOIN employees e ON e.id_card = c.id_card
""").fetchall()
print(f"身份证跨表相同的行对: {len(id_intersection)} 组 (可能为 0, 数据独立生成)")
id_bad = 0
for cid, eid, _ in id_intersection:
    ci = dst.execute("SELECT id_card FROM customers WHERE id=?", (cid,)).fetchone()[0]
    ei = dst.execute("SELECT id_card FROM employees WHERE id=?", (eid,)).fetchone()[0]
    if ci != ei:
        id_bad += 1
print(f"身份证跨表不一致数: {id_bad}")

assert bad == 0 and name_bad == 0 and id_bad == 0
print("\nCROSS-TABLE DETERMINISM PASSED")
