"""Web API smoke test: 配置 -> 跑作业 -> 报告零错误."""
from __future__ import annotations

import os
import time

import pytest

from submask.app import create_app
from submask.state import StateStore


@pytest.fixture()
def client(tmp_path, source_db):
    app = create_app(str(tmp_path))
    app.testing = True
    return app.test_client(), str(tmp_path), source_db


def test_full_job_flow_through_api(client):
    c, workdir, source_db = client

    # 1. 连接数据源
    resp = c.post("/api/datasource", json={"path": source_db})
    assert resp.status_code == 200
    snap = resp.get_json()
    assert len(snap["tables"]) == 30

    # 2. 推断 + 全部确认
    candidates = c.post("/api/infer").get_json()
    assert len(candidates) >= 15
    c.post("/api/edges/confirm", json={"edges": candidates})
    graph = c.get("/api/graph").get_json()
    assert any(e["origin"] == "inferred" for e in graph["edges"])

    # 3. 配置规则 / 脱敏 / 设置
    rules = {
        "customers": {"mode": "seed",
                      "where": "level_id >= 3 AND status='active'",
                      "percent": 100},
        "order_items": {"mode": "percent", "where": None, "percent": 55},
    }
    masking = {
        "customers": {"name": "name", "phone": "phone", "id_card": "id_card",
                      "bank_card": "bank_card", "email": "email"},
        "employees": {"name": "name", "phone": "phone", "id_card": "id_card"},
        "addresses": {"receiver": "name", "phone": "phone"},
    }
    c.post("/api/config", json={
        "rules": rules, "masking": masking,
        "settings": {"date_shift_days": 90, "salt": "api-salt"}})
    saved = c.get("/api/config").get_json()
    assert saved["rules"]["customers"]["mode"] == "seed"

    # 4. 跑作业并等待后台线程
    job_id = c.post("/api/jobs").get_json()["job_id"]
    for _ in range(60):
        job = c.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "success", job

    # 5. 报告零错误
    report = c.get(f"/api/jobs/{job_id}/report").get_json()
    assert report["validation"]["foreign_key_errors"] == 0
    assert report["validation"]["format_errors"] == 0
    assert report["validation"]["zero_error"] is True
    assert report["date_shift_days"] == 90

    # 6. 目标库文件确实落盘
    assert os.path.exists(os.path.join(workdir, "output",
                                       f"subset_{job_id}.db"))
