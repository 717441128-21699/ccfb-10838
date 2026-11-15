"""需求 4/5/6: 格式合法、校验位、确定性、一一对应、日期平移."""
from __future__ import annotations

import sqlite3

import pytest

from submask.masking import (MaskingEngine, id_card_valid, id_check_digit,
                             luhn_valid, phone_valid)


@pytest.fixture()
def engine(tmp_state):
    return MaskingEngine(sqlite3.connect(tmp_state), salt="unit-salt")


def test_phone_format_and_determinism(engine):
    fake = engine.mask_value("phone", "13812345678")
    assert phone_valid(fake)
    assert engine.mask_value("phone", "13812345678") == fake
    # 不同原值 -> 不同假值 (同列一一对应)
    others = {engine.mask_value("phone", f"1390000000{i}") for i in range(1, 6)}
    assert len(others) == 5 and fake not in others


def test_id_card_check_digit_and_birth_kept(engine):
    body = "44030519920815432"
    source = body + id_check_digit(body)
    fake = engine.mask_value("id_card", source)
    assert id_card_valid(fake)
    assert fake[6:14] == "19920815"          # 生日段保留, 由日期平移统一处理
    assert fake != source


def test_bank_card_length_and_luhn(engine):
    from scripts.generate_demo import make_bank_card
    import random
    source = make_bank_card(random.Random(7))
    assert luhn_valid(source)
    fake = engine.mask_value("bank_card", source)
    assert len(fake) == len(source)
    assert luhn_valid(fake)


def test_cross_table_same_value_same_fake(engine):
    a = engine.mask_value("name", "张三")
    b = engine.mask_value("name", "张三")     # 模拟不同表中的同一原值
    assert a == b and a != "张三"


def test_persistence_across_engines(tmp_state):
    e1 = MaskingEngine(sqlite3.connect(tmp_state), salt="persist")
    fake = e1.mask_value("email", "bob@corp.example")
    e2 = MaskingEngine(sqlite3.connect(tmp_state), salt="persist")
    assert e2.mask_value("email", "bob@corp.example") == fake


def test_date_shift_preserves_intervals(engine):
    shifted = [engine.shift_date(d, 90) for d in
               ("2024-01-01", "2024-03-01", "2024-03-01 08:30:00")]
    assert shifted == ["2024-03-31", "2024-05-30", "2024-05-30 08:30:00"]
    # 间隔不变: 两个日期差仍是 60 天
    from datetime import datetime
    d0 = datetime.strptime(shifted[0], "%Y-%m-%d")
    d1 = datetime.strptime(shifted[1], "%Y-%m-%d")
    assert (d1 - d0).days == 60
