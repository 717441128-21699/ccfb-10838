"""Referential-closure subset extraction.

规则模型:
- seed 表: WHERE 条件选出种子行 (例如客户).
- percent 表 (大表): 按比例 *从可达行中* 确定性等距抽样.
- 其余表: 只有被关系带到时才纳入, 带到多少收多少, 全部可达行都收.

闭包保证:
- 向上 (child -> parent): 被保留行引用的父行一律补齐, 含环形引用.
- 向下 (parent -> child): 引用了被保留父行的子行带出; percent 表抽样后,
  它引用的父行仍会被向上闭包补齐, 因此目标库不会出现悬空外键.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .graph import RelationshipGraph

CHUNK = 800


@dataclass
class TableRule:
    mode: str = "reach"          # seed | percent | reach
    where: str | None = None     # seed 模式的 WHERE 子句
    percent: float = 100.0       # percent 模式


@dataclass
class ExtractionResult:
    selected: dict[str, list[int]] = field(default_factory=dict)
    rule_sizes: dict[str, int] = field(default_factory=dict)
    seed_selected: dict[str, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def table_count(self, table: str) -> int:
        return len(self.selected.get(table, []))


def _chunked(seq, size=CHUNK):
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def _placeholders(values) -> str:
    return ",".join("?" for _ in values)


class Extractor:
    def __init__(self, conn, graph: RelationshipGraph,
                 rules: dict[str, TableRule]):
        self.conn = conn
        self.graph = graph
        self.rules = rules
        self.kept: dict[str, set[int]] = {}
        self._seed_snapshot: dict[str, set[int]] = {}

    # ------------------------------------------------------------------ #
    def _seed_rows(self, table: str, rule: TableRule) -> set[int]:
        # 只有 seed 模式预置行; percent 表在闭包完成后对"可达行"统一抽样,
        # 避免全表预抽样把不可达行也拉进来导致比例失真.
        if rule.mode == "seed":
            sql = f'SELECT rowid FROM "{table}"'
            if rule.where:
                sql += f" WHERE {rule.where}"
            sql += " ORDER BY rowid"
            return {r[0] for r in self.conn.execute(sql).fetchall()}
        return set()

    @staticmethod
    def _stride_sample(ordered: list[int], target: int) -> list[int]:
        """确定性等距抽样: 同一输入永远得到同一结果."""
        n = len(ordered)
        if target <= 0:
            return []
        if target >= n:
            return ordered
        if target == 1:
            return [ordered[0]]
        step = n / target
        return [ordered[int(i * step)] for i in range(target)]

    # ------------------------------------------------------------------ #
    def _add(self, table: str, rowids) -> bool:
        bucket = self.kept.setdefault(table, set())
        before = len(bucket)
        bucket.update(rowids)
        return len(bucket) > before

    def _upward(self, table: str) -> list[str]:
        """补齐当前表保留行引用到的所有父行."""
        changed_tables = []
        rowids = self.kept.get(table, set())
        if not rowids:
            return changed_tables
        for edge in self.graph.parent_edges(table):
            new_parents: set[int] = set()
            for chunk in _chunked(sorted(rowids)):
                ph = _placeholders(chunk)
                vals = self.conn.execute(
                    f'SELECT DISTINCT c."{edge.column}" FROM "{table}" c '
                    f'WHERE c.rowid IN ({ph}) AND c."{edge.column}" IS NOT NULL',
                    chunk).fetchall()
                fk_values = [v[0] for v in vals]
                if not fk_values:
                    continue
                for vchunk in _chunked(fk_values):
                    ph2 = _placeholders(vchunk)
                    pr = self.conn.execute(
                        f'SELECT rowid FROM "{edge.ref_table}" '
                        f'WHERE "{edge.ref_column}" IN ({ph2})', vchunk
                    ).fetchall()
                    new_parents.update(r[0] for r in pr)
            if new_parents and self._add(edge.ref_table, new_parents):
                changed_tables.append(edge.ref_table)
        return changed_tables

    def _downward(self, table: str) -> list[str]:
        """带出引用了当前表保留行的全部子行 (比例抽样在闭包后统一做)."""
        changed_tables = []
        rowids = self.kept.get(table, set())
        if not rowids:
            return changed_tables
        # 父表保留行的 PK 值 (子表外键引用的是 PK 值, 不是 rowid)
        for edge in self.graph.child_edges(table):
            pk_values: set = set()
            for chunk in _chunked(sorted(rowids)):
                ph = _placeholders(chunk)
                rows = self.conn.execute(
                    f'SELECT "{edge.ref_column}" FROM "{table}" '
                    f'WHERE rowid IN ({ph})', chunk).fetchall()
                pk_values.update(r[0] for r in rows if r[0] is not None)
            if not pk_values:
                continue
            child_rowids: list[int] = []
            for vchunk in _chunked(sorted(pk_values)):
                ph = _placeholders(vchunk)
                rows = self.conn.execute(
                    f'SELECT rowid FROM "{edge.table}" '
                    f'WHERE "{edge.column}" IN ({ph}) ORDER BY rowid',
                    vchunk).fetchall()
                child_rowids.extend(r[0] for r in rows)
            if child_rowids and self._add(edge.table, child_rowids):
                changed_tables.append(edge.table)
        return changed_tables

    def _apply_percent_sampling(self) -> dict[str, int]:
        """对 percent 表的可达行做确定性等距抽样, 返回各表抽样后保留数."""
        sampled_counts: dict[str, int] = {}
        for table, rule in self.rules.items():
            if rule.mode != "percent" or table not in self.kept:
                continue
            reachable = sorted(self.kept[table])
            target = round(len(reachable) * rule.percent / 100.0)
            if rule.percent >= 100 or target >= len(reachable):
                sampled_counts[table] = len(reachable)
                continue
            chosen = set(self._stride_sample(reachable, target))
            self.kept[table] = chosen
            sampled_counts[table] = len(chosen)
        return sampled_counts

    def _upward_fixpoint(self) -> None:
        """只做向上闭包直到固定点: 补齐被保留行引用的父行 (修复抽样悬空)."""
        worklist = list(self.kept.keys())
        queued = set(worklist)
        while worklist:
            table = worklist.pop(0)
            queued.discard(table)
            for nxt in self._upward(table):
                if nxt not in queued:
                    worklist.append(nxt)
                    queued.add(nxt)

    # ------------------------------------------------------------------ #
    def run(self) -> ExtractionResult:
        result = ExtractionResult()
        worklist: list[str] = []

        # 1. 种子 / 预抽样 (快照存独立冻结副本, 不被后续闭包污染)
        for table, rule in self.rules.items():
            rows = self._seed_rows(table, rule)
            self._seed_snapshot[table] = set(rows)
            if rows:
                self.kept[table] = set(rows)
                worklist.append(table)
                result.rule_sizes[table] = len(rows)

        if not worklist:
            result.notes.append("没有配置任何种子规则, 未抽取数据")
            return result

        # 2. 完整双向闭包到固定点 (环形引用靠集合收敛自然处理)
        queued = set(worklist)
        while worklist:
            table = worklist.pop(0)
            queued.discard(table)
            for nxt in self._upward(table) + self._downward(table):
                if nxt not in queued:
                    worklist.append(nxt)
                    queued.add(nxt)

        # 3. 对 percent 表的可达行精确等距抽样 (此时 kept 是完整可达集)
        result.rule_sizes.update(self._apply_percent_sampling())

        # 4. 抽样后再做向上闭包: 补齐被保留行引用的父行, 杜绝悬空外键
        self._upward_fixpoint()

        result.selected = {t: sorted(ids) for t, ids in self.kept.items() if ids}
        result.seed_selected = {
            t: sorted(rows) for t, rows in self._seed_snapshot.items() if rows}

        # 3. 未被关系带到的表
        all_tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()}
        unreached = sorted(all_tables - set(result.selected))
        for t in unreached:
            result.notes.append(f"表 {t} 与种子集合无可达关系, 未抽取")
        return result
