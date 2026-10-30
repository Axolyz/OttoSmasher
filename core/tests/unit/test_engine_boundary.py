"""引擎边界（所有者 2026-10-30）：引擎模块只做计算，不引用资料库、业务服务、命令目录与命令行。

这样“原始能力”可以单独调用，以后真要把引擎拆成独立的包，基本只是挪目录。唯一允许的 core 依赖是错误类型（``core.errors``）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import ottosmasher

ROOT = Path(ottosmasher.__file__).parent
ENGINE = ["media", "lang", "models", "domain", "algo", "jobs/speech.py", "jobs/primitives.py"]
FORBIDDEN = ("store", "core", "api", "cli")
ALLOWED = {"core.errors"}


def _files():
    for e in ENGINE:
        p = ROOT / e
        yield from ([p] if p.suffix == ".py" else sorted(p.rglob("*.py")))


def _imports(path: Path):
    pkg = path.relative_to(ROOT).with_suffix("").parts[:-1]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(pkg[: len(pkg) - node.level + 1])
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = (node.module or "").removeprefix("ottosmasher.") if (node.module or "").startswith("ottosmasher") else ""
            if mod:
                yield node.lineno, mod
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("ottosmasher."):
                    yield node.lineno, a.name.removeprefix("ottosmasher.")


def test_engine_does_not_import_library_or_services():
    bad = []
    for f in _files():
        for line, mod in _imports(f):
            top = mod.split(".")[0]
            if top in FORBIDDEN and not any(mod == a or mod.startswith(a + ".") for a in ALLOWED):
                bad.append(f"{f.relative_to(ROOT)}:{line} imports {mod}")
    assert not bad, "\n".join(bad)
