"""Build the target SQLite database: full DDL (incl. confirmed inferred FKs),
masked data load inside a deferred-FK transaction, indexes recreated."""
from __future__ import annotations

import re
import sqlite3

from .graph import RelationshipGraph
from .masking import MaskingEngine
from .schema import table_columns, unique_indexes

DATE_TYPE_TOKENS = ("DATE", "DATETIME", "TIMESTAMP")
DATE_NAME_RE = re.compile(r"(_at|_date|date$|time$|_time)$", re.IGNORECASE)
DATE_VALUE_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


def _is_date_column(src_conn, table: str, col, sample: object) -> bool:
    if col.type.upper() in DATE_TYPE_TOKENS:
        return True
    if isinstance(sample, str) and DATE_VALUE_RE.match(sample):
        return True
    if sample is None and DATE_NAME_RE.search(col.name):
        # 抽样行为空时退回列名启发式
        return True
    return False


def _col_def(col) -> str:
    parts = [f'"{col.name}"', col.type or "TEXT"]
    if col.pk == 1:
        parts.append("PRIMARY KEY")
    if col.notnull and col.pk == 0:
        parts.append("NOT NULL")
    if col.default is not None:
        parts.append(f"DEFAULT {col.default}")
    return " ".join(parts)


def build_ddl(conn, table: str, graph: RelationshipGraph) -> str:
    cols = table_columns(conn, table)
    pk_cols = [c.name for c in sorted((c for c in cols if c.pk),
                                      key=lambda c: c.pk)]
    composite_pk = len(pk_cols) > 1
    defs = []
    for col in cols:
        parts = [f'"{col.name}"', col.type or "TEXT"]
        if col.pk == 1 and not composite_pk:
            parts.append("PRIMARY KEY")
        if col.notnull and col.pk == 0:
            parts.append("NOT NULL")
        if col.default is not None:
            parts.append(f"DEFAULT {col.default}")
        defs.append(" ".join(parts))
    if composite_pk:
        defs.append("PRIMARY KEY (" + ", ".join(f'"{c}"' for c in pk_cols) + ")")
    for edge in graph.parent_edges(table):
        defs.append(
            f'FOREIGN KEY ("{edge.column}") REFERENCES '
            f'"{edge.ref_table}" ("{edge.ref_column}") '
            f"DEFERRABLE INITIALLY DEFERRED")
    return f'CREATE TABLE "{table}" (\n  ' + ",\n  ".join(defs) + "\n)"


def create_target(src_conn, dst_path: str, graph: RelationshipGraph,
                  tables: list[str]) -> sqlite3.Connection:
    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA foreign_keys=ON")
    for table in tables:
        dst.execute(build_ddl(src_conn, table, graph))
        for idx_cols in unique_indexes(src_conn, table):
            name = f"uq_{table}_" + "_".join(idx_cols)
            cols = ", ".join(f'"{c}"' for c in idx_cols)
            dst.execute(f'CREATE UNIQUE INDEX "{name}" ON "{table}" ({cols})')
    dst.commit()
    return dst


def load_data(src_conn, dst: sqlite3.Connection, graph: RelationshipGraph,
              selected: dict[str, list[int]],
              masking_cfg: dict[str, dict[str, str]],
              engine: MaskingEngine,
              date_shift_days: int = 0) -> dict[str, int]:
    """Insert selected rows with masking applied. Single deferred transaction.

    日期整体平移: 除显式 date 策略外, 所有 DATE/DATETIME/TIMESTAMP/TEXT 日期列
    统一平移 date_shift_days 天, 保证先后顺序与间隔不变.
    """
    counts: dict[str, int] = {}
    dst.execute("PRAGMA defer_foreign_keys=ON")
    dst.execute("BEGIN")
    try:
        for table, rowids in selected.items():
            cols = table_columns(src_conn, table)
            col_names = [c.name for c in cols]
            col_masks = masking_cfg.get(table, {})
            # 日期列: 声明类型 / 列名启发式 / 实际数据形态三者综合判断
            date_cols = set()
            if date_shift_days:
                for col in cols:
                    if col_masks.get(col.name):
                        continue
                    sample = src_conn.execute(
                        f'SELECT "{col.name}" FROM "{table}" '
                        f'WHERE "{col.name}" IS NOT NULL LIMIT 1').fetchone()
                    if sample and _is_date_column(
                            src_conn, table, col, sample[0]):
                        date_cols.add(col.name)
            placeholders = ",".join("?" for _ in col_names)
            collist = ", ".join(f'"{c}"' for c in col_names)
            insert = (f'INSERT INTO "{table}" ({collist}) '
                      f"VALUES ({placeholders})")
            total = 0
            for rid in rowids:
                row = src_conn.execute(
                    f'SELECT {collist} FROM "{table}" WHERE rowid=?',
                    (rid,)).fetchone()
                masked = []
                for name, value in zip(col_names, row):
                    strategy = col_masks.get(name)
                    if strategy:
                        value = engine.mask_value(strategy, value,
                                                  date_shift_days)
                    elif date_shift_days and name in date_cols:
                        value = engine.shift_date(value, date_shift_days)
                    masked.append(value)
                dst.execute(insert, masked)
                total += 1
            counts[table] = total
        dst.execute("COMMIT")
    except Exception:
        dst.execute("ROLLBACK")
        raise
    return counts
