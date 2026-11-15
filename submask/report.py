"""Per-job report: per-table counts, masking coverage, validation results."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .masking import MaskingEngine
from .schema import row_count
from .validator import foreign_key_violations, format_violations


@dataclass
class JobReport:
    job_id: str
    source_db: str
    target_db: str
    started_at: str
    finished_at: str
    status: str
    date_shift_days: int
    tables: list[dict] = field(default_factory=list)
    masking: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


def build_report(job_id: str, source_conn, target_conn, *,
                 source_db: str, target_db: str,
                 started_at: str, finished_at: str,
                 status: str, extraction_result, load_counts: dict[str, int],
                 masking_cfg: dict[str, dict[str, str]],
                 engine: MaskingEngine,
                 date_shift_days: int,
                 error: str | None = None) -> JobReport:
    report = JobReport(
        job_id=job_id, source_db=source_db, target_db=target_db,
        started_at=started_at, finished_at=finished_at, status=status,
        date_shift_days=date_shift_days, notes=list(extraction_result.notes),
        error=error,
    )

    # 每张表: 源行数 / 种子行数 / 闭包带入 / 抽取行数 / 占比
    all_tables = [r[0] for r in source_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for table in all_tables:
        src_total = row_count(source_conn, table)
        kept = extraction_result.table_count(table)
        seed_n = len(extraction_result.seed_selected.get(table, []))
        report.tables.append({
            "table": table,
            "source_rows": src_total,
            "seed_rows": seed_n,
            "closure_added": max(kept - seed_n, 0),
            "extracted_rows": load_counts.get(table, kept),
            "percent": round(100.0 * kept / src_total, 2) if src_total else 0,
            "reached": table in extraction_result.selected,
        })

    # 敏感字段处理情况: 每个脱敏列的行数与映射条目数
    for table, col_masks in sorted(masking_cfg.items()):
        for column, strategy in sorted(col_masks.items()):
            n = target_conn.execute(
                f'SELECT COUNT(*) FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL AND "{column}" != ""'
            ).fetchone()[0]
            report.masking.setdefault(table, {})[column] = {
                "strategy": strategy, "rows_masked": n,
                "distinct_fake_values": engine.mapping_size(strategy),
            }

    # 目标库外键 + 格式校验
    fk_bad = foreign_key_violations(target_conn)
    fmt_bad = format_violations(target_conn, masking_cfg)
    report.validation = {
        "foreign_key_errors": len(fk_bad),
        "foreign_key_samples": fk_bad[:20],
        "format_errors": len(fmt_bad),
        "format_samples": fmt_bad[:20],
        "zero_error": not fk_bad and not fmt_bad,
    }
    return report
