"""Relationship graph over declared + user-confirmed inferred edges."""
from __future__ import annotations

from dataclasses import dataclass

from .schema import ForeignKey


@dataclass(frozen=True)
class Edge:
    table: str        # child
    column: str
    ref_table: str    # parent
    ref_column: str
    origin: str       # "declared" | "inferred"

    def key(self) -> tuple:
        return (self.table, self.column, self.ref_table, self.ref_column)


class RelationshipGraph:
    """Edges point child -> parent (FK direction)."""

    def __init__(self, edges: list[Edge]):
        self.edges = list(edges)
        self._parents: dict[str, list[Edge]] = {}
        self._children: dict[str, list[Edge]] = {}
        self.nodes: set[str] = set()
        for e in self.edges:
            self.nodes.update((e.table, e.ref_table))
            self._parents.setdefault(e.table, []).append(e)
            self._children.setdefault(e.ref_table, []).append(e)

    @classmethod
    def build(cls, declared: list[ForeignKey],
              confirmed_inferred: list[ForeignKey]) -> "RelationshipGraph":
        edges = [Edge(f.table, f.column, f.ref_table, f.ref_column, "declared")
                 for f in declared]
        edges += [Edge(f.table, f.column, f.ref_table, f.ref_column, "inferred")
                  for f in confirmed_inferred]
        seen, unique = set(), []
        for e in edges:
            if e.key() not in seen:
                seen.add(e.key())
                unique.append(e)
        return cls(unique)

    def parent_edges(self, table: str) -> list[Edge]:
        """Outgoing FK edges: rows of this table reference parents."""
        return self._parents.get(table, [])

    def child_edges(self, table: str) -> list[Edge]:
        """Incoming edges: rows of child tables reference this table."""
        return self._children.get(table, [])

    def to_dict(self) -> dict:
        return {
            "nodes": sorted(self.nodes),
            "edges": [
                {"table": e.table, "column": e.column,
                 "ref_table": e.ref_table, "ref_column": e.ref_column,
                 "origin": e.origin}
                for e in self.edges
            ],
        }
