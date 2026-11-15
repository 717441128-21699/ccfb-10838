"""Infer undeclared foreign keys from column names and actual data overlap."""
from __future__ import annotations

from dataclasses import dataclass

from .schema import declared_fks, list_tables, table_columns, table_pk


def singularize(name: str) -> str:
    rules = (("ies", "y"), ("sses", "ss"), ("ses", "s"), ("xes", "x"),
             ("ches", "ch"), ("shes", "sh"), ("s", ""))
    for suffix, repl in rules:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)] + repl
    return name


@dataclass
class InferredEdge:
    table: str
    column: str
    ref_table: str
    ref_column: str
    name_score: float
    containment: float       # distinct child values found in parent / all distinct
    distinct_values: int
    matched_values: int
    confidence: float

    def key(self) -> tuple:
        return (self.table, self.column, self.ref_table, self.ref_column)


def _name_score(column: str, parent_table: str, parent_pk: str, self_ref: bool) -> float:
    stem = singularize(parent_table)
    if column == f"{stem}_id":
        return 1.0
    if column == parent_pk and parent_pk != "id":
        return 0.9
    if column.endswith(f"{stem}_id"):
        return 0.8                       # billing_address_id -> addresses
    if self_ref:
        # 自引用只认层级/归属类命名, 避免 warehouse_id 误判到本表
        if column in ("parent_id", "manager_id", "leader_id", "pid"):
            return 0.6
        return 0.0
    if column in ("manager_id", "leader_id") and "employee" in parent_table:
        return 0.7                       # departments.manager_id -> employees
    if column.endswith("_id"):
        col_stem = column[:-3]
        if col_stem and stem and (col_stem in stem or stem in col_stem):
            return 0.55
    return 0.0


def infer_foreign_keys(conn, min_overlap: int = 1,
                       min_containment: float = 0.8) -> list[InferredEdge]:
    """Suggest FK candidates. A child column keeps only its best parent match."""
    tables = list_tables(conn)
    pk_of = {t: (table_pk(conn, t) or ["rowid"])[0] for t in tables}
    declared = {(f.table, f.column): f for f in declared_fks(conn)}
    candidates: list[InferredEdge] = []

    for child in tables:
        cols = table_columns(conn, child)
        for col in cols:
            if col.pk:
                continue
            if not (col.name.endswith("_id") or col.name in pk_of.values()):
                continue
            if (child, col.name) in declared:
                continue
            best: InferredEdge | None = None
            for parent in tables:
                parent_pk = pk_of[parent]
                score = _name_score(col.name, parent, parent_pk,
                                    self_ref=(child == parent))
                if score <= 0:
                    continue
                stats = conn.execute(
                    f'SELECT COUNT(DISTINCT c.v), '
                    f'SUM(CASE WHEN p."{parent_pk}" IS NOT NULL THEN 1 ELSE 0 END) '
                    f'FROM (SELECT DISTINCT "{col.name}" AS v FROM "{child}" '
                    f'WHERE "{col.name}" IS NOT NULL) c '
                    f'LEFT JOIN (SELECT DISTINCT "{parent_pk}" FROM "{parent}") p '
                    f'ON c.v = p."{parent_pk}"'
                ).fetchone()
                total, matched = stats[0] or 0, stats[1] or 0
                if total < min_overlap:
                    continue
                containment = matched / total
                if containment < min_containment:
                    continue
                confidence = round(0.4 * score + 0.6 * containment, 3)
                edge = InferredEdge(child, col.name, parent, parent_pk, score,
                                    round(containment, 3), total, matched,
                                    confidence)
                if best is None or (confidence, score) > (best.confidence,
                                                           best.name_score):
                    best = edge
            if best:
                candidates.append(best)

    candidates.sort(key=lambda e: (-e.confidence, e.table, e.column))
    return candidates
