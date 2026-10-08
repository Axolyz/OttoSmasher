"""实测记录落库（规格 14 §14.7、13 §13.4）：按（模型、设备设置）保存，任何带模型推理的任务都可以在结果里交回 ``probes``。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..store.db import transaction
from .clock import now_iso
from .edits import dumps


def record_probes(conn: sqlite3.Connection, probes: list[dict[str, Any]]) -> None:
    ts = now_iso()
    with transaction(conn):
        for pr in probes:
            conn.execute(
                "INSERT INTO model_probe(model, device_setting, file_sha, status, ep_node_counts, error, tested_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(model, device_setting) DO UPDATE SET file_sha=excluded.file_sha, status=excluded.status,"
                " ep_node_counts=excluded.ep_node_counts, error=excluded.error, tested_at=excluded.tested_at",
                (pr["model"], dumps(pr["device"]), pr.get("file_sha"), pr["status"], dumps(pr["nodes"]) if pr.get("nodes") is not None else None,
                 pr.get("error"), ts),
            )
