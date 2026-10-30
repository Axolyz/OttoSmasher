"""程序自带文件的位置：源码运行时是仓库，发布版是 .app 的 Contents/Resources（阶段 10，2026-10-30）。

发布版的启动方（应用主进程、``otto`` 启动器）设 ``OTTO_RESOURCES``；没设就是源码运行，按包所在位置找仓库根目录。
两种布局下相对路径相同：``third_party/``、``app/renderer/i18n/locales/``、``tools/otto``；发布版另有 ``models/``（随包的模型权重）。
"""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # core/ottosmasher → 仓库根目录（源码运行时）


def packaged() -> bool:
    return bool(os.environ.get("OTTO_RESOURCES"))


def root() -> Path:
    env = os.environ.get("OTTO_RESOURCES")
    return Path(env) if env else REPO


def default_workspace() -> Path:
    """没指定工作区时：源码运行 = 仓库里的 dev-workspace；发布版 = ~/Documents/OttoSmasher Workspace（ROADMAP L3）。"""
    return Path.home() / "Documents" / "OttoSmasher Workspace" if packaged() else REPO / "dev-workspace"


def bundled_models() -> Path | None:
    """随包的模型权重（发布版）；源码运行时没有，权重都在工作区的 Models/。"""
    d = root() / "models"
    return d if packaged() and d.is_dir() else None
