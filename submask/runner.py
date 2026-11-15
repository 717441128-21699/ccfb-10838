"""End-to-end job orchestration: extract -> build target -> mask -> validate."""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid

from .extraction import Extractor, TableRule
from .graph import RelationshipGraph
from .masking import MaskingEngine
from .report import build_report
from .schema import ForeignKey, declared_fks
from .state import StateStore, utcnow
from .target_builder import create_target, load_data


class JobRunner:
    def __init__(self, store: StateStore, workdir: str):
        self.store = store
        self.workdir = workdir
        os.makedirs(os.path.join(workdir, "output"), exist_ok=True)
        os.makedirs(os.path.join(workdir, "reports"), exist_ok=True)
        self._threads: dict[str, threading.Thread] = {}

    # ------------------------------------------------------------------ #
    def start(self) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.store.add_job(job_id, utcnow())
        t = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        self._threads[job_id] = t
        t.start()
        return job_id

    # ------------------------------------------------------------------ #
    def _run(self, job_id: str) -> None:
        started = utcnow()
        target_path = os.path.join(self.workdir, "output", f"subset_{job_id}.db")
        report_path = os.path.join(self.workdir, "reports", f"{job_id}.json")
        src = None
        try:
            ds = self.store.get("datasource", {})
            src_path = ds["path"]
            edges_conf = self.store.get("confirmed_edges", [])
            rules_conf = self.store.get("rules", {})
            masking_cfg = self.store.get("masking", {})
            settings = self.store.get("settings", {})
            shift = int(settings.get("date_shift_days", 0))
            salt = settings.get("salt", "submask-v1")

            src = sqlite3.connect(src_path)
            declared = declared_fks(src)
            confirmed = [ForeignKey(**e) for e in edges_conf]
            graph = RelationshipGraph.build(declared, confirmed)

            rules = {t: TableRule(mode=r.get("mode", "reach"),
                                  where=r.get("where"),
                                  percent=float(r.get("percent", 100)))
                     for t, r in rules_conf.items()}
            result = Extractor(src, graph, rules).run()

            if os.path.exists(target_path):
                os.remove(target_path)
            dst = create_target(src, target_path, graph,
                                list(result.selected))

            engine = MaskingEngine(self.store.conn, salt=salt)
            counts = load_data(src, dst, graph, result.selected,
                               masking_cfg, engine, shift)

            finished = utcnow()
            report = build_report(
                job_id, src, dst, source_db=src_path, target_db=target_path,
                started_at=started, finished_at=finished,
                status="success", extraction_result=result,
                load_counts=counts, masking_cfg=masking_cfg, engine=engine,
                date_shift_days=shift)
            report.save(report_path)
            self.store.finish_job(job_id, finished, "success", report_path,
                                  report.to_dict())
            dst.close()
        except Exception as exc:  # noqa: BLE001 — 记录到作业报告
            finished = utcnow()
            detail = {"error": repr(exc)}
            self.store.finish_job(job_id, finished, "failed", report_path,
                                  detail)
        finally:
            if src is not None:
                src.close()
