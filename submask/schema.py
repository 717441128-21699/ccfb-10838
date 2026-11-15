"""SQLite schema introspection: tables, columns, PKs, declared foreign keys."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    cid: int
    name: str
    type: str
    notnull: bool
    pk: int          # 0 = not part of PK, otherwise 1-based position in PK
    default: object


@dataclass(frozen=True)
class ForeignKey:
    table: str        # child table
    column: str       # child column
    ref_table: str    # parent table
    ref_column: str   # parent column

    def key(self) -> tuple:
        return (self.table, self.column, self.ref_table, self.ref_column)


def list_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def table_columns(conn, table: str) -> list[Column]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [Column(cid=r[0], name=r[1], type=r[2] or "", notnull=bool(r[3]),
                   pk=r[5] or 0, default=r[4]) for r in rows]


def table_pk(conn, table: str) -> list[str]:
    cols = table_columns(conn, table)
    pk_cols = sorted((c for c in cols if c.pk), key=lambda c: c.pk)
    return [c.name for c in pk_cols]


def declared_fks(conn) -> list[ForeignKey]:
    """All foreign keys declared in the schema."""
    out: list[ForeignKey] = []
    for table in list_tables(conn):
        rows = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        # rows: id, seq, table(referenced), from, to, on_update, on_delete, match
        for r in rows:
            out.append(ForeignKey(
                table=table, column=r[3], ref_table=r[2],
                ref_column=r[4] or "id",
            ))
    return out


def row_count(conn, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def table_ddl(conn, table: str) -> str:
    return conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]


def unique_indexes(conn, table: str) -> list[list[str]]:
    """Return column lists of user-defined UNIQUE indexes (PK autoindex skipped)."""
    result = []
    for idx in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        # seq, name, unique, origin, partial
        name, unique, origin = idx[1], idx[2], idx[3]
        if origin in ("c", "u") and unique:
            info = conn.execute(f'PRAGMA index_info("{name}")').fetchall()
            result.append([r[2] for r in info])
    return result


def schema_snapshot(conn) -> dict:
    """Full snapshot used by the web API and inference engine."""
    tables = {}
    for t in list_tables(conn):
        cols = table_columns(conn, t)
        tables[t] = {
            "columns": [
                {"name": c.name, "type": c.type, "notnull": c.notnull,
                 "pk": c.pk, "default": c.default}
                for c in cols
            ],
            "pk": table_pk(conn, t),
            "row_count": row_count(conn, t),
        }
    fks = [f.__dict__ for f in declared_fks(conn)]
    return {"tables": tables, "declared_fks": fks}
