"""HTTP-level smoke test against a running server (python scripts/smoke_web.py <base>)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5050"
SRC = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "demo_source.db")).replace("\\", "/")


def call(path: str, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    if method is None:
        method = "POST" if payload is not None else "GET"
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    snap = call("/api/datasource", {"path": SRC})
    print(f"tables: {len(snap['tables'])}, declared FKs: "
          f"{len(snap['declared_fks'])}")
    assert len(snap["tables"]) == 30

    candidates = call("/api/infer", method="POST")
    print(f"inferred candidates: {len(candidates)}")
    assert len(candidates) >= 15
    call("/api/edges/confirm", {"edges": candidates})
    graph = call("/api/graph", method="GET")
    print(f"graph edges: {len(graph['edges'])}")

    call("/api/config", {
        "rules": {
            "customers": {"mode": "seed",
                          "where": "level_id >= 3 AND status='active'",
                          "percent": 100},
            "order_items": {"mode": "percent", "where": None, "percent": 55},
            "login_logs": {"mode": "percent", "where": None, "percent": 40},
        },
        "masking": {
            "customers": {"name": "name", "phone": "phone",
                          "id_card": "id_card", "bank_card": "bank_card",
                          "email": "email"},
            "employees": {"name": "name", "phone": "phone",
                          "id_card": "id_card", "bank_card": "bank_card"},
            "addresses": {"receiver": "name", "phone": "phone"},
        },
        "settings": {"date_shift_days": 180, "salt": "submask-v1"},
    })

    job_id = call("/api/jobs", method="POST")["job_id"]
    print(f"job started: {job_id}")
    for _ in range(60):
        time.sleep(1)
        job = call(f"/api/jobs/{job_id}", method="GET")
        if job["status"] != "running":
            break
    print(f"job status: {job['status']}")
    assert job["status"] == "success", job

    report = call(f"/api/jobs/{job_id}/report", method="GET")
    v = report["validation"]
    print(f"FK errors: {v['foreign_key_errors']}")
    print(f"format errors: {v['format_errors']}")
    print(f"zero error: {v['zero_error']}")
    print(f"tables in report: {len(report['tables'])}")
    masked = sum(len(cols) for cols in report["masking"].values())
    print(f"masked columns: {masked}")
    for t in report["tables"][:6]:
        print(f"  {t['table']:<20} src={t['source_rows']:<6} "
              f"seed={t['seed_rows']:<4} closure={t['closure_added']:<6} "
              f"kept={t['extracted_rows']}")
    assert v["zero_error"] is True
    print("\nWEB SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
