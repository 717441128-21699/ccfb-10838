"""Generate the 30-table demo source database.

特性:
- 30 张业务表, 电商 + 会员 + 组织域.
- 环形引用: customers.default_address_id <-> addresses.customer_id;
  employees.manager_id (自引用); departments.manager_id <-> employees.department_id;
  orders.parent_order_id (自引用).
- 未声明外键 (仅按命名/数据推断): customer_levels, customer_services,
  user_roles, point_accounts, product_reviews, audit_logs, orders 等多处.
- 敏感字段均为格式合法的真实形态数据 (身份证校验位、银行卡 Luhn).
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from submask.masking import ID_CHECK, ID_WEIGHTS, id_check_digit, luhn_check_digit

TABLES_DDL = [
    """CREATE TABLE customer_levels (
        level_id INTEGER PRIMARY KEY,
        level_name TEXT NOT NULL,
        min_points INTEGER NOT NULL)""",
    """CREATE TABLE customers (
        id INTEGER PRIMARY KEY,
        customer_no TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        id_card TEXT NOT NULL,
        bank_card TEXT,
        email TEXT,
        gender TEXT,
        level_id INTEGER NOT NULL,
        register_date TEXT NOT NULL,
        status TEXT NOT NULL,
        default_address_id INTEGER)""",
    """CREATE TABLE addresses (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        receiver TEXT NOT NULL,
        phone TEXT NOT NULL,
        province TEXT, city TEXT, district TEXT,
        detail TEXT, is_default INTEGER DEFAULT 0,
        FOREIGN KEY (customer_id) REFERENCES customers(id))""",
    """CREATE TABLE regions (
        id INTEGER PRIMARY KEY,
        region_name TEXT NOT NULL,
        parent_id INTEGER,
        level INTEGER NOT NULL)""",
    """CREATE TABLE departments (
        id INTEGER PRIMARY KEY,
        dept_name TEXT NOT NULL,
        parent_id INTEGER,
        manager_id INTEGER)""",
    """CREATE TABLE employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        id_card TEXT NOT NULL,
        bank_card TEXT,
        department_id INTEGER NOT NULL,
        manager_id INTEGER,
        hire_date TEXT,
        FOREIGN KEY (department_id) REFERENCES departments(id))""",
    """CREATE TABLE categories (
        id INTEGER PRIMARY KEY,
        category_name TEXT NOT NULL,
        parent_id INTEGER,
        FOREIGN KEY (parent_id) REFERENCES categories(id))""",
    """CREATE TABLE suppliers (
        id INTEGER PRIMARY KEY,
        supplier_name TEXT NOT NULL,
        contact_name TEXT,
        phone TEXT,
        address TEXT)""",
    """CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        sku TEXT NOT NULL UNIQUE,
        product_name TEXT NOT NULL,
        category_id INTEGER NOT NULL,
        supplier_id INTEGER NOT NULL,
        price REAL NOT NULL,
        status TEXT,
        FOREIGN KEY (category_id) REFERENCES categories(id),
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id))""",
    """CREATE TABLE warehouses (
        id INTEGER PRIMARY KEY,
        warehouse_name TEXT NOT NULL,
        region_id INTEGER,
        address TEXT)""",
    """CREATE TABLE inventory (
        id INTEGER PRIMARY KEY,
        product_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        updated_at TEXT)""",
    """CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        order_no TEXT NOT NULL UNIQUE,
        customer_id INTEGER NOT NULL,
        employee_id INTEGER,
        address_id INTEGER,
        parent_order_id INTEGER,
        order_status TEXT NOT NULL,
        total_amount REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (employee_id) REFERENCES employees(id),
        FOREIGN KEY (address_id) REFERENCES addresses(id))""",
    """CREATE TABLE order_items (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        subtotal REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id))""",
    """CREATE TABLE payments (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        pay_method TEXT NOT NULL,
        amount REAL NOT NULL,
        paid_at TEXT,
        status TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id))""",
    """CREATE TABLE shipments (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        carrier TEXT,
        tracking_no TEXT,
        shipped_at TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(id))""",
    """CREATE TABLE coupons (
        id INTEGER PRIMARY KEY,
        coupon_name TEXT NOT NULL,
        discount REAL NOT NULL,
        expire_date TEXT)""",
    """CREATE TABLE customer_coupons (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        coupon_id INTEGER NOT NULL,
        used_order_id INTEGER,
        status TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(id),
        FOREIGN KEY (coupon_id) REFERENCES coupons(id))""",
    """CREATE TABLE point_accounts (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        balance INTEGER NOT NULL,
        updated_at TEXT)""",
    """CREATE TABLE point_transactions (
        id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL,
        change_points INTEGER NOT NULL,
        reason TEXT,
        created_at TEXT,
        FOREIGN KEY (account_id) REFERENCES point_accounts(id))""",
    """CREATE TABLE product_reviews (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        order_item_id INTEGER,
        score INTEGER NOT NULL,
        content TEXT,
        created_at TEXT)""",
    """CREATE TABLE returns (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        reason TEXT,
        amount REAL,
        status TEXT,
        created_at TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id))""",
    """CREATE TABLE messages (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        channel TEXT,
        title TEXT,
        content TEXT,
        sent_at TEXT,
        is_read INTEGER DEFAULT 0,
        FOREIGN KEY (customer_id) REFERENCES customers(id))""",
    """CREATE TABLE customer_services (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        employee_id INTEGER,
        order_id INTEGER,
        subject TEXT,
        content TEXT,
        status TEXT,
        created_at TEXT)""",
    """CREATE TABLE roles (
        id INTEGER PRIMARY KEY,
        role_name TEXT NOT NULL)""",
    """CREATE TABLE permissions (
        id INTEGER PRIMARY KEY,
        perm_name TEXT NOT NULL)""",
    """CREATE TABLE role_permissions (
        role_id INTEGER NOT NULL,
        permission_id INTEGER NOT NULL,
        PRIMARY KEY (role_id, permission_id),
        FOREIGN KEY (role_id) REFERENCES roles(id),
        FOREIGN KEY (permission_id) REFERENCES permissions(id))""",
    """CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        employee_id INTEGER NOT NULL,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        status TEXT,
        FOREIGN KEY (employee_id) REFERENCES employees(id))""",
    """CREATE TABLE user_roles (
        user_id INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, role_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (role_id) REFERENCES roles(id))""",
    """CREATE TABLE login_logs (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        login_ip TEXT,
        login_at TEXT,
        success INTEGER)""",
    """CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        table_name TEXT,
        row_id INTEGER,
        action TEXT,
        created_at TEXT)""",
]

# 建表后补环形外键 (SQLite 允许 ALTER 受限, 这里用第二个 DDL 脚本加索引/回填)
UNDECLARED_NOTE = """
-- 以下列在 DDL 中刻意不声明 FOREIGN KEY, 交给推断引擎 + 人工勾选:
-- customers.level_id            -> customer_levels.level_id
-- customers.default_address_id  -> addresses.id
-- departments.manager_id        -> employees.id
-- employees.manager_id          -> employees.id (自引用)
-- regions.parent_id             -> regions.id (自引用)
-- warehouses.region_id          -> regions.id
-- inventory.product_id/warehouse_id -> products/warehouses
-- orders.parent_order_id        -> orders.id (自引用)
-- customer_coupons.used_order_id -> orders.id
-- point_accounts.customer_id    -> customers.id
-- product_reviews.customer_id/product_id/order_item_id
-- customer_services.customer_id/employee_id/order_id
-- user_roles.user_id/role_id (按命名推断到 users/roles)
-- login_logs.user_id, audit_logs.user_id
"""

SURNAMES = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何林高罗")
GIVEN = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋",
         "勇", "艳", "杰", "娟", "涛", "明", "超", "霞", "平", "刚",
         "文", "华", "雪", "鹏", "宇", "婷婷", "欣怡", "子涵", "浩然"]
CITIES = [("北京市", "北京市", "朝阳区"), ("上海市", "上海市", "浦东新区"),
          ("广州市", "广东省", "天河区"), ("深圳市", "广东省", "南山区"),
          ("杭州市", "浙江省", "西湖区"), ("南京市", "江苏省", "玄武区"),
          ("成都市", "四川省", "武侯区"), ("武汉市", "湖北省", "武昌区")]


def make_id_card(rng: random.Random, birth: date) -> str:
    region = rng.choice(["110101", "310104", "440103", "440305",
                         "330102", "320102", "510104", "420102"])
    body = f"{region}{birth:%Y%m%d}{rng.randrange(1000):03d}"
    return body + id_check_digit(body)


def make_bank_card(rng: random.Random) -> str:
    prefix = rng.choice(["622202", "621700", "622848", "622666", "955880"])
    payload = prefix + "".join(str(rng.randrange(10)) for _ in range(9))
    return payload + luhn_check_digit(payload)


def make_phone(rng: random.Random) -> str:
    return rng.choice(["138", "139", "150", "158", "186", "188", "177", "199"]) \
        + f"{rng.randrange(10_000_000, 100_000_000)}"


def make_name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN)


def generate(db_path: str, seed: int = 20261115) -> dict:
    rng = random.Random(seed)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    for ddl in TABLES_DDL:
        conn.execute(ddl)

    base = date(2021, 1, 1)

    def d(offset: int) -> str:
        return (base + timedelta(days=offset)).strftime("%Y-%m-%d")

    def dt(offset: int) -> str:
        return (base + timedelta(days=offset, hours=rng.randrange(8, 20),
                                 minutes=rng.randrange(60))).strftime(
            "%Y-%m-%d %H:%M:%S")

    # ---- 基础数据 ---- #
    levels = [(1, "普通", 0), (2, "银卡", 1000), (3, "金卡", 5000),
              (4, "铂金", 20000), (5, "钻石", 50000)]
    conn.executemany("INSERT INTO customer_levels VALUES (?,?,?)", levels)

    regions = []
    for i, (prov, city, dist) in enumerate(CITIES, start=1):
        regions.append((i, prov, None, 1))
        cid = 100 + i
        regions.append((cid, city, i, 2))
        regions.append((200 + i, dist, cid, 3))
    conn.executemany("INSERT INTO regions VALUES (?,?,?,?)", regions)

    depts = [(1, "总裁办", None, None), (2, "销售部", 1, None),
             (3, "技术部", 1, None), (4, "客服部", 2, None),
             (5, "仓储部", 1, None)]
    conn.executemany("INSERT INTO departments VALUES (?,?,?,?)", depts)

    # 员工: manager_id 先空后回填, 形成自引用环
    emp_rows = []
    for i in range(1, 61):
        birth = date(1980 + rng.randrange(0, 20), rng.randrange(1, 13),
                     rng.randrange(1, 28))
        emp_rows.append((i, make_name(rng), make_phone(rng),
                         make_id_card(rng, birth), make_bank_card(rng),
                         rng.randrange(1, 6), None,
                         d(-rng.randrange(200, 2000))))
    conn.executemany(
        "INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)", emp_rows)
    for i in range(2, 61):                       # 经理自引用环
        conn.execute("UPDATE employees SET manager_id=? WHERE id=?",
                     (rng.randrange(1, i), i))
    conn.execute("UPDATE employees SET manager_id=1 WHERE id=1")
    # 部门 <-> 员工 环
    for dept_id, mgr in [(1, 1), (2, 7), (3, 13), (4, 21), (5, 31)]:
        conn.execute("UPDATE departments SET manager_id=? WHERE id=?",
                     (mgr, dept_id))

    cats = [(1, "数码", None), (2, "手机", 1), (3, "笔记本", 1),
            (4, "家居", None), (5, "厨具", 4), (6, "食品", None),
            (7, "零食", 6)]
    conn.executemany("INSERT INTO categories VALUES (?,?,?)", cats)
    suppliers = [(i, f"供应商{i:02d}", make_name(rng), make_phone(rng),
                  rng.choice(CITIES)[0] + "某园区") for i in range(1, 13)]
    conn.executemany("INSERT INTO suppliers VALUES (?,?,?,?,?)", suppliers)

    products = []
    for i in range(1, 201):
        products.append((
            i, f"SKU{i:05d}", f"商品{i:03d}", rng.randrange(1, 8),
            rng.randrange(1, 13), round(rng.uniform(9.9, 4999), 2),
            rng.choice(["on_sale", "on_sale", "off_sale"])))
    conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", products)

    warehouses = [(i, f"仓库{i}", rng.randrange(1, len(regions) + 1),
                   rng.choice(CITIES)[0] + "物流园") for i in range(1, 9)]
    conn.executemany("INSERT INTO warehouses VALUES (?,?,?,?)", warehouses)

    inv = []
    inv_id = 1
    for pid in range(1, 201):
        for wid in rng.sample(range(1, 9), rng.randrange(2, 5)):
            inv.append((inv_id, pid, wid, rng.randrange(0, 5000),
                        dt(-rng.randrange(0, 30))))
            inv_id += 1
    conn.executemany("INSERT INTO inventory VALUES (?,?,?,?,?)", inv)

    # ---- 客户 (500) ---- #
    cust_rows = []
    for i in range(1, 501):
        birth = date(1965 + rng.randrange(0, 40), rng.randrange(1, 13),
                     rng.randrange(1, 28))
        reg = -rng.randrange(1, 1500)
        cust_rows.append((
            i, f"C{i:06d}", make_name(rng), make_phone(rng),
            make_id_card(rng, birth),
            make_bank_card(rng) if rng.random() < 0.85 else None,
            f"user{i}@example.com", rng.choice(["M", "F"]),
            rng.choices([1, 2, 3, 4, 5], weights=[40, 25, 20, 10, 5])[0],
            d(reg), rng.choice(["active", "active", "active", "frozen"]),
            None))
    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", cust_rows)

    # 刻意构造跨表同值: 前 10 名员工复用客户 1..10 的身份证与银行卡,
    # 验证同一身份证/银行卡号在 employees 与 customers 两表脱敏结果一致
    for i in range(1, 11):
        idc, bc = conn.execute(
            "SELECT id_card, bank_card FROM customers WHERE id=?", (i,)
        ).fetchone()
        conn.execute(
            "UPDATE employees SET id_card=?, bank_card=? WHERE id=?",
            (idc, bc, i))

    # 地址: 每客户 1-3 个, 回填 default_address_id 构成环
    addr_id = 1
    # 刻意构造跨表同值: 前 30 个客户的首个地址复用本人手机号/姓名,
    # 用于验证"同一原值在所有表脱成同一假值"
    shared = {}
    for cid in range(1, 501):
        n_addr = rng.randrange(1, 4)
        first = addr_id
        for k in range(n_addr):
            prov, city, dist = rng.choice(CITIES)
            if cid <= 30 and k == 0:
                receiver = conn.execute(
                    "SELECT name FROM customers WHERE id=?", (cid,)).fetchone()[0]
                phone = conn.execute(
                    "SELECT phone FROM customers WHERE id=?", (cid,)).fetchone()[0]
                shared[cid] = (receiver, phone)
            else:
                receiver, phone = make_name(rng), make_phone(rng)
            conn.execute(
                "INSERT INTO addresses VALUES (?,?,?,?,?,?,?,?,?)",
                (addr_id, cid, receiver, phone,
                 prov, city, dist, f"路{rng.randrange(1, 200)}号",
                 1 if addr_id == first else 0))
            addr_id += 1
        conn.execute("UPDATE customers SET default_address_id=? WHERE id=?",
                     (first, cid))

    # ---- 订单 (3000) + 明细 + 支付 + 物流 ---- #
    orders, items, pays, ships, returns, coupons_used = [], [], [], [], [], []
    coupon_ids = []
    for i in range(1, 41):
        cid = conn.execute(
            "INSERT INTO coupons VALUES (?,?,?,?)",
            (i, f"优惠券{i}", round(rng.uniform(5, 200), 2),
             d(rng.randrange(30, 400))))
        coupon_ids.append(i)

    item_id = 1
    pay_id = ship_id = ret_id = 1
    for oid in range(1, 3001):
        cid = rng.randrange(1, 501)
        created = -rng.randrange(1, 1200)
        status = rng.choice(["paid", "shipped", "completed", "completed",
                             "completed", "cancelled"])
        n_items = rng.randrange(1, 5)
        total = 0.0
        parent_candidates = [None, None, None]
        if oid > 1:
            parent_candidates.append(rng.randrange(1, oid))
        parent = rng.choice(parent_candidates)
        orders.append((oid, f"O{oid:08d}", cid,
                       rng.randrange(1, 61),
                       conn.execute(
                           "SELECT id FROM addresses WHERE customer_id=? "
                           "ORDER BY id LIMIT 1", (cid,)).fetchone()[0],
                       parent, status, 0.0, dt(created)))
        for _ in range(n_items):
            pid = rng.randrange(1, 201)
            price = conn.execute(
                "SELECT price FROM products WHERE id=?", (pid,)).fetchone()[0]
            qty = rng.randrange(1, 4)
            sub = round(price * qty, 2)
            total += sub
            items.append((item_id, oid, pid, qty, price, sub))
            item_id += 1
        conn.execute("UPDATE orders SET total_amount=? WHERE id=?",
                     (round(total, 2), oid))
        if status != "cancelled":
            pays.append((pay_id, oid, rng.choice(["alipay", "wechat", "card"]),
                         round(total, 2), dt(created), "success"))
            pay_id += 1
        if status in ("shipped", "completed"):
            ships.append((ship_id, oid, rng.randrange(1, 9),
                          rng.choice(["顺丰", "京东物流", "中通"]),
                          f"SF{rng.randrange(10**11, 10**12)}", dt(created)))
            ship_id += 1
        if status == "completed" and rng.random() < 0.06:
            returns.append((ret_id, oid, rng.choice(["质量问题", "不想要了",
                                                      "尺寸不符"]),
                            round(total * rng.uniform(0.3, 1), 2),
                            rng.choice(["approved", "pending"]), dt(created)))
            ret_id += 1
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", orders)
    conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", items)
    conn.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", pays)
    conn.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?)", ships)
    conn.executemany("INSERT INTO returns VALUES (?,?,?,?,?,?)", returns)

    # ---- 会员资产 ---- #
    for cid in range(1, 501):
        acc = conn.execute(
            "INSERT INTO point_accounts VALUES (?,?,?,?)",
            (cid, cid, rng.randrange(0, 30000), d(-rng.randrange(0, 60)))).lastrowid
        for _ in range(rng.randrange(0, 6)):
            conn.execute(
                "INSERT INTO point_transactions VALUES (?,?,?,?,?)",
                (None, acc, rng.choice([-100, -50, 50, 100, 200, 500]),
                 rng.choice(["消费", "签到", "兑换", "退款"]),
                 d(-rng.randrange(0, 300))))
        for cp in rng.sample(coupon_ids, rng.randrange(0, 4)):
            used_oid = rng.randrange(1, 3001) if rng.random() < 0.4 else None
            conn.execute(
                "INSERT INTO customer_coupons VALUES (?,?,?,?,?)",
                (None, cid, cp, used_oid,
                 "used" if used_oid else "unused"))

    # ---- 评价 ---- #
    for _ in range(1500):
        conn.execute(
            "INSERT INTO product_reviews VALUES (?,?,?,?,?,?,?)",
            (None, rng.randrange(1, 501), rng.randrange(1, 201),
             rng.randrange(1, item_id), rng.randrange(1, 6),
             rng.choice(["好评", "不错", "一般般", "回购"]),
             d(-rng.randrange(0, 900))))

    # ---- 消息 / 客服 ---- #
    for _ in range(2000):
        conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
            (None, rng.randrange(1, 501), rng.choice(["sms", "app", "email"]),
             "通知", rng.choice(["促销提醒", "订单状态更新", "积分到期提醒"]),
             d(-rng.randrange(0, 400)), rng.randrange(0, 2)))
    for _ in range(800):
        conn.execute(
            "INSERT INTO customer_services VALUES (?,?,?,?,?,?,?,?)",
            (None, rng.randrange(1, 501), rng.randrange(1, 61),
             rng.randrange(1, 3001), rng.choice(["咨询", "投诉", "售后"]),
             "问题描述", rng.choice(["open", "closed"]),
             d(-rng.randrange(0, 500))))

    # ---- RBAC / 用户 / 日志 ---- #
    conn.executemany("INSERT INTO roles VALUES (?,?)",
                     [(1, "admin"), (2, "operator"), (3, "auditor"),
                      (4, "service")])
    conn.executemany("INSERT INTO permissions VALUES (?,?)",
                     [(i, f"perm_{i}") for i in range(1, 11)])
    for rid in range(1, 5):
        for pid in rng.sample(range(1, 11), rng.randrange(3, 8)):
            conn.execute("INSERT INTO role_permissions VALUES (?,?)",
                         (rid, pid))
    for uid in range(1, 61):
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?)",
                     (uid, uid, f"user{uid:03d}",
                      f"hash{rng.randrange(10**8, 10**9):x}",
                      rng.choice(["active", "active", "locked"])))
        conn.execute("INSERT INTO user_roles VALUES (?,?)",
                     (uid, rng.randrange(1, 5)))
    for _ in range(3000):
        conn.execute("INSERT INTO login_logs VALUES (?,?,?,?,?)",
                     (None, rng.randrange(1, 61),
                      f"10.0.{rng.randrange(0, 255)}.{rng.randrange(1, 255)}",
                      dt(-rng.randrange(0, 200)), rng.choice([1, 1, 1, 0])))
    for _ in range(1200):
        conn.execute("INSERT INTO audit_logs VALUES (?,?,?,?,?,?)",
                     (None, rng.randrange(1, 61),
                      rng.choice(["orders", "customers", "payments"]),
                      rng.randrange(1, 3000),
                      rng.choice(["insert", "update", "delete"]),
                      dt(-rng.randrange(0, 200))))

    conn.commit()

    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT name, (SELECT COUNT(*) FROM pragma_table_info(name)) "
        "FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    row_counts = {}
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        row_counts[name] = conn.execute(
            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    conn.close()
    return row_counts


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "demo_source.db")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    stats = generate(out)
    print(f"demo database: {out}")
    print(f"tables: {len(stats)}")
    for t, n in stats.items():
        print(f"  {t:22s} {n:>7d}")
    total = sum(stats.values())
    print(f"total rows: {total}")
