"""Persistent state store: datasource, confirmed edges, rules, masking config,
job history. One SQLite database under the work directory."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime


def utcnow() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                report_path TEXT,
                detail TEXT);
            """)
        self.conn.commit()

    # ---------------- key/value config ---------------- #
    def get(self, key: str, default=None):
        row = self.conn.execute(
            "SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False, default=str)))
        self.conn.commit()

    # ---------------- jobs ---------------- #
    def add_job(self, job_id: str, started_at: str) -> None:
        self.conn.execute(
            "INSERT INTO jobs(job_id, started_at, status) VALUES(?, ?, 'running')",
            (job_id, started_at))
        self.conn.commit()

    def finish_job(self, job_id: str, finished_at: str, status: str,
                   report_path: str, detail: dict) -> None:
        self.conn.execute(
            "UPDATE jobs SET finished_at=?, status=?, report_path=?, detail=? "
            "WHERE job_id=?",
            (finished_at, status, report_path,
             json.dumps(detail, ensure_ascii=False), job_id))
        self.conn.commit()

    def list_jobs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY started_at DESC LIMIT 100").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"]) if d["detail"] else None
            out.append(d)
        return out

    def get_job(self, job_id: str) -> dict | None:
        r = self.conn.execute(
            "SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["detail"] = json.loads(d["detail"]) if d["detail"] else None
        return d
