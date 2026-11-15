"""Flask web application: datasource / graph / rules / masking / jobs."""
from __future__ import annotations

import json
import os
import sqlite3

from flask import Flask, jsonify, request, send_from_directory

from .graph import RelationshipGraph
from .inference import infer_foreign_keys
from .runner import JobRunner
from .schema import declared_fks, schema_snapshot
from .state import StateStore

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


def create_app(workdir: str) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    store = StateStore(os.path.join(workdir, "submask_state.db"))
    runner = JobRunner(store, workdir)

    def source_conn():
        ds = store.get("datasource")
        if not ds or not os.path.exists(ds["path"]):
            raise FileNotFoundError("数据源未配置或文件不存在")
        return sqlite3.connect(ds["path"])

    # ---------------- 页面 ---------------- #
    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    # ---------------- 数据源 ---------------- #
    @app.post("/api/datasource")
    def set_datasource():
        data = request.get_json(force=True)
        path = data["path"]
        if not os.path.exists(path):
            return jsonify({"error": f"文件不存在: {path}"}), 400
        conn = sqlite3.connect(path)
        try:
            snap = schema_snapshot(conn)
        finally:
            conn.close()
        store.set("datasource", {"path": os.path.abspath(path)})
        store.set("confirmed_edges", [])
        return jsonify(snap)

    @app.get("/api/schema")
    def get_schema():
        conn = source_conn()
        try:
            return jsonify(schema_snapshot(conn))
        finally:
            conn.close()

    @app.post("/api/infer")
    def run_inference():
        conn = source_conn()
        try:
            candidates = infer_foreign_keys(conn)
            return jsonify([c.__dict__ for c in candidates])
        finally:
            conn.close()

    @app.get("/api/graph")
    def get_graph():
        conn = source_conn()
        try:
            declared = declared_fks(conn)
        finally:
            conn.close()
        from .schema import ForeignKey
        confirmed = [ForeignKey(**e) for e in store.get("confirmed_edges", [])]
        return jsonify(RelationshipGraph.build(declared, confirmed).to_dict())

    @app.post("/api/edges/confirm")
    def confirm_edges():
        data = request.get_json(force=True)
        edges = data.get("edges", [])
        valid = []
        for e in edges:
            valid.append({
                "table": e["table"], "column": e["column"],
                "ref_table": e["ref_table"], "ref_column": e["ref_column"],
            })
        store.set("confirmed_edges", valid)
        return jsonify({"saved": len(valid)})

    # ---------------- 抽取规则 / 脱敏 / 设置 ---------------- #
    @app.get("/api/config")
    def get_config():
        return jsonify({
            "rules": store.get("rules", {}),
            "masking": store.get("masking", {}),
            "settings": store.get("settings", {}),
        })

    @app.post("/api/config")
    def save_config():
        data = request.get_json(force=True)
        if "rules" in data:
            store.set("rules", data["rules"])
        if "masking" in data:
            store.set("masking", data["masking"])
        if "settings" in data:
            store.set("settings", data["settings"])
        return jsonify({"ok": True})

    # ---------------- 作业 ---------------- #
    @app.post("/api/jobs")
    def create_job():
        job_id = runner.start()
        return jsonify({"job_id": job_id})

    @app.get("/api/jobs")
    def list_jobs():
        return jsonify(runner.store.list_jobs())

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id: str):
        job = runner.store.get_job(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        return jsonify(job)

    @app.get("/api/jobs/<job_id>/report")
    def job_report(job_id: str):
        job = runner.store.get_job(job_id)
        if not job or not job["report_path"]:
            return jsonify({"error": "report not ready"}), 404
        if not os.path.exists(job["report_path"]):
            return jsonify({"error": "report file missing"}), 404
        with open(job["report_path"], encoding="utf-8") as f:
            return jsonify(json.load(f))

    return app
