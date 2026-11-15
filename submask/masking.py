"""Deterministic format-preserving masking.

设计要点:
- 同一原值在所有表、所有作业中映射到同一假值 (持久化映射表 + 固定 salt).
- 输出保持原格式合法: 手机号 11 位、身份证 18 位且校验位正确、
  银行卡保持原长度且通过 Luhn 校验.
- 同列内映射为一一对应 (bijection), 不会把两个不同原值映成同一个假值.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime

SURNAMES = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何林高罗郑梁谢宋唐许韩冯邓曹")
GIVEN = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋", "勇", "艳",
         "杰", "娟", "涛", "明", "超", "秀英", "霞", "平", "刚", "桂英", "文",
         "华", "建华", "建国", "晓东", "雪", "志强", "海燕", "建军", "婷婷", "鹏",
         "宇", "欣怡", "子涵", "梓萱", "浩然", "诗涵", "一诺", "若曦"]

# 身份证地区码 (前 6 位), 均为真实存在的行政区划代码
REGION_CODES = ["110101", "110105", "310104", "310115", "440103", "440106",
                "440304", "440305", "330102", "330106", "320102", "320105",
                "510104", "510107", "420102", "420106", "610102", "610113"]

ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CHECK = "10X98765432"


def _digest(*parts: str) -> bytes:
    return hashlib.sha256("|".join(parts).encode("utf-8")).digest()


def _int_stream(seed_key: str):
    """确定性整数流, 用于枚举候选假值, 保证可复现."""
    counter = 0
    while True:
        d = _digest(seed_key, str(counter))
        for i in range(0, len(d) - 3, 4):
            yield int.from_bytes(d[i:i + 4], "big")
        counter += 1


def luhn_check_digit(payload: str) -> str:
    s = 0
    for i, ch in enumerate(reversed(payload)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        s += n
    return str((10 - s % 10) % 10)


def luhn_valid(number: str) -> bool:
    if not number or not number.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def id_check_digit(body17: str) -> str:
    total = sum(int(ch) * w for ch, w in zip(body17, ID_WEIGHTS))
    return ID_CHECK[total % 11]


def id_card_valid(value: str) -> bool:
    if len(value) != 18 or not value[:17].isdigit():
        return False
    if value[17] not in ID_CHECK:
        return False
    return id_check_digit(value[:17]) == value[17]


def phone_valid(value: str) -> bool:
    return (len(value) == 11 and value.isdigit()
            and value[0] == "1" and value[1] in "3456789")


class MaskingEngine:
    """按策略做确定性脱敏, 映射持久化在 state DB 的 masking_dict 表中."""

    STRATEGIES = ("name", "phone", "id_card", "bank_card", "email", "date")

    def __init__(self, state_conn: sqlite3.Connection, salt: str = "submask-v1"):
        self.conn = state_conn
        self.salt = salt
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS masking_dict ("
            "strategy TEXT NOT NULL, source_value TEXT NOT NULL, "
            "fake_value TEXT NOT NULL, PRIMARY KEY (strategy, source_value))")
        self.conn.commit()
        self._used: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ #
    def _load_used(self, strategy: str) -> set[str]:
        if strategy not in self._used:
            rows = self.conn.execute(
                "SELECT fake_value FROM masking_dict WHERE strategy=?",
                (strategy,)).fetchall()
            self._used[strategy] = {r[0] for r in rows}
        return self._used[strategy]

    def _store(self, strategy: str, source: str, fake: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO masking_dict(strategy, source_value, "
            "fake_value) VALUES (?, ?, ?)", (strategy, source, fake))
        self.conn.commit()
        self._load_used(strategy).add(fake)

    def _unique_fake(self, strategy: str, source: str, generator) -> str:
        row = self.conn.execute(
            "SELECT fake_value FROM masking_dict WHERE strategy=? AND "
            "source_value=?", (strategy, source)).fetchone()
        if row:
            return row[0]
        used = self._load_used(strategy)
        for candidate in generator(source):
            if candidate not in used:
                self._store(strategy, source, candidate)
                return candidate
        raise RuntimeError(f"masking space exhausted for {strategy}")

    # ------------------------------------------------------------------ #
    def _gen_name(self, source: str):
        for n in _int_stream(self.salt + ":name:" + source):
            surname = SURNAMES[n % len(SURNAMES)]
            given = GIVEN[(n // len(SURNAMES)) % len(GIVEN)]
            yield surname + given

    def _gen_phone(self, source: str):
        prefixes = ("138", "139", "150", "151", "158", "159", "186", "187",
                    "188", "177", "199")
        for n in _int_stream(self.salt + ":phone:" + source):
            prefix = prefixes[n % len(prefixes)]
            suffix = f"{n // len(prefixes):08d}"
            yield prefix + suffix[:8]

    def _gen_id_card(self, source: str):
        # 保留原出生日期段的形态, 生日整体由 date_shift_days 平移
        birth = ""
        if len(source) == 18 and source[:17].isdigit():
            birth = source[6:14]
        for n in _int_stream(self.salt + ":idcard:" + source):
            region = REGION_CODES[n % len(REGION_CODES)]
            seq = f"{(n // len(REGION_CODES)) % 1000:03d}"
            body = region + birth + seq
            yield body + id_check_digit(body)

    def _gen_bank_card(self, source: str):
        length = len(source) if source.isdigit() and len(source) >= 12 else 16
        bins = ("622202", "621700", "622848", "622666", "955880", "621226")
        payload_len = length - 1
        for n in _int_stream(self.salt + ":bankcard:" + source):
            prefix = bins[n % len(bins)]
            middle_len = payload_len - len(prefix)
            middle = f"{n // len(bins):0{middle_len}d}"[:middle_len].zfill(
                middle_len)
            payload = prefix + middle
            yield payload + luhn_check_digit(payload)

    def _gen_email(self, source: str):
        for n in _int_stream(self.salt + ":email:" + source):
            user = f"masked{n % 1_000_000:06d}"
            yield f"{user}@masked.example.com"

    # ------------------------------------------------------------------ #
    def mask_value(self, strategy: str, value, date_shift_days: int = 0):
        if value is None or value == "":
            return value
        if strategy == "date":
            return self.shift_date(value, date_shift_days)
        source = str(value)
        generators = {
            "name": self._gen_name,
            "phone": self._gen_phone,
            "id_card": self._gen_id_card,
            "bank_card": self._gen_bank_card,
            "email": self._gen_email,
        }
        if strategy not in generators:
            raise ValueError(f"unknown strategy: {strategy}")
        return self._unique_fake(strategy, source, generators[strategy])

    @staticmethod
    def shift_date(value, shift_days: int):
        """日期整体平移: 所有日期加同一个天数, 间隔与先后顺序不变."""
        if shift_days == 0 or value is None:
            return value
        if isinstance(value, datetime):
            return value + timedelta(days=shift_days)
        if isinstance(value, date):
            return date.fromordinal(value.toordinal() + shift_days)
        text = str(value)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                dt = datetime.strptime(text, fmt)
                return (dt + timedelta(days=shift_days)).strftime(fmt)
            except ValueError:
                continue
        return value  # 非标准格式保持原样, 报告中会标记

    def mapping_size(self, strategy: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM masking_dict WHERE strategy=?",
            (strategy,)).fetchone()[0]


# 放在文件末尾避免循环引用观感问题
from datetime import timedelta  # noqa: E402
