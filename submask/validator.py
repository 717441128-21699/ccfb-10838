"""Post-load validation: foreign-key integrity and masked-format checks."""
from __future__ import annotations

import sqlite3

from .masking import id_card_valid, luhn_valid, phone_valid


def foreign_key_violations(conn) -> list[dict]:
    """PRAGMA foreign_key_check: zero rows means referential integrity holds."""
    conn.execute("PRAGMA foreign_keys=ON")
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    # table, rowid, parent, fkid
    return [{"table": r[0], "rowid": r[1], "parent_table": r[2],
             "fk_index": r[3]} for r in rows]


def format_violations(conn, masking_cfg: dict[str, dict[str, str]]) -> list[dict]:
    """Validate every column that was assigned a format-bearing strategy."""
    violations = []
    validators = {
        "phone": phone_valid,
        "id_card": id_card_valid,
        "bank_card": luhn_valid,
    }
    for table, col_masks in masking_cfg.items():
        for column, strategy in col_masks.items():
            validator = validators.get(strategy)
            if validator is None:
                continue
            try:
                rows = conn.execute(
                    f'SELECT rowid, "{column}" FROM "{table}" '
                    f'WHERE "{column}" IS NOT NULL AND "{column}" != ""'
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            for rowid, value in rows:
                if not validator(str(value)):
                    violations.append({
                        "table": table, "column": column, "rowid": rowid,
                        "strategy": strategy, "value": str(value)[:32],
                    })
    return violations
