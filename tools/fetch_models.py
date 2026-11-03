"""把四个模型的权重下载到开发工作区 dev-workspace/Models（直链与 SHA-256 来自 models/registry.py）。

用法：.venv/bin/python tools/fetch_models.py（Windows 用 .venv/Scripts/python.exe）
已存在且 SHA 一致的文件跳过；SHA 不一致一律报错，不覆盖、不将就。给没有图形界面的机器用，平时也可以在 设置 → 环境与模型 里下载。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "dev-workspace" / "Models"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from ottosmasher.models.registry import MODELS as SPECS
    from ottosmasher.models.registry import sha256_file

    for spec in SPECS:
        for f in spec.files:
            if f.role != "weight":
                continue
            dest = MODELS / f.rel_path
            if dest.exists():
                if sha256_file(dest) != f.sha256:
                    raise SystemExit(f"已存在但 SHA-256 不一致，请人工检查：{dest}")
                print(f"已就位 {f.rel_path}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"下载 {spec.url_hint}")
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
                with urllib.request.urlopen(spec.url_hint, timeout=300) as resp:  # noqa: S310 — 固定的 https 地址
                    shutil.copyfileobj(resp, tmp)
            part = Path(tmp.name)
            got = sha256_file(part)
            if got != f.sha256:
                part.unlink()
                raise SystemExit(f"SHA-256 不一致：{spec.url_hint}\n  期望 {f.sha256}\n  实际 {got}")
            part.replace(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
