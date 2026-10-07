"""时间与 ID。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def now_iso() -> str:
    """UTC 时间，毫秒精度，ISO 8601（入库统一格式）。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    """不透明的随机 128 位十六进制 ID（ARCHITECTURE §4）。"""
    return uuid.uuid4().hex
