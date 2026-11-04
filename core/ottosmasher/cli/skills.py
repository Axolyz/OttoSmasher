"""工作区里的 agent skills（所有者 2026-11-04，ARCHITECTURE §15.5）：可以改的做法放在 ``<工作区>/Agent/skills/``，格式是 Agent Skills 标准的文件夹。

内置版本随应用分发（``guide/skills/<语言>/`` + ``guide/skills/common/``），第一次用时复制到工作区并记下哈希；之后按 dpkg 处理配置文件的办法更新：
- 用户没改过 → 换成新版本；用户改过、内置没变 → 不动；两边都改了 → 新版本放在旁边的 ``<文件>.new``，等用户或 agent 合并，删掉 ``.new`` 就算处理完，同一版本不再提示；
- 用户删掉的不补回来；内置版本不再有的文件：没改过的删掉，改过的留下。
语言在第一次复制时定下，之后换界面语言不会把文件换掉。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

BUNDLED = Path(__file__).resolve().parent / "guide" / "skills"
MANIFEST = ".otto-skills.json"
NEW = ".new"
COMMAND_RE = re.compile(r"`([a-z]+\.[a-zA-Z0-9]+)")
NOT_COMMANDS = ("video", "binding", "error", "result", "c")  # 结果里的字段（video.path、result.path……）与脚本里的 c.call


def skills_dir(ws: Path) -> Path:
    return ws / "Agent" / "skills"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


def bundled_files(lang: str) -> dict[str, bytes]:
    """这个语言的内置文件：相对路径（``名字/SKILL.md``）→ 内容。"""
    files: dict[str, bytes] = {}
    for root in (BUNDLED / "common", BUNDLED / lang):
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                files[p.relative_to(root).as_posix()] = p.read_bytes()
    return files


def _load_manifest(d: Path) -> dict[str, Any]:
    try:
        m = json.loads((d / MANIFEST).read_text(encoding="utf-8"))
        if isinstance(m, dict) and isinstance(m.get("files"), dict):
            return m
    except (OSError, ValueError):
        pass
    return {"files": {}}


def sync(ws: Path, lang: str) -> dict[str, Any]:
    """把内置 skill 同步到工作区。可以重复运行，没有变化时不写文件。"""
    d = skills_dir(ws)
    manifest = _load_manifest(d)
    before = json.dumps(manifest, sort_keys=True)
    lang = manifest.get("lang") if manifest.get("lang") in ("zh-CN", "en") else lang
    bundled = bundled_files(lang)
    files: dict[str, dict[str, Any]] = manifest["files"]
    report: dict[str, list[str]] = {"installed": [], "updated": [], "conflicts": []}
    for rel, data in bundled.items():
        new_sha = _sha(data)
        dest, side = d / rel, d / (rel + NEW)
        entry = files.get(rel)
        if entry is None:
            if not dest.exists():
                _write(dest, data)
                report["installed"].append(rel)
                files[rel] = {"installed": new_sha, "offered": new_sha}
            elif _sha(dest.read_bytes()) == new_sha:
                files[rel] = {"installed": new_sha, "offered": new_sha}
            else:  # 用户自己有个同名文件：当作改过的
                _write(side, data)
                report["conflicts"].append(rel)
                files[rel] = {"installed": None, "offered": new_sha}
            continue
        if not dest.exists():  # 用户删掉的不补回来
            entry["offered"] = new_sha
            continue
        cur_sha = _sha(dest.read_bytes())
        if cur_sha == new_sha:
            files[rel] = {"installed": new_sha, "offered": new_sha}
            side.unlink(missing_ok=True)
        elif cur_sha == entry.get("installed"):
            _write(dest, data)
            report["updated"].append(rel)
            files[rel] = {"installed": new_sha, "offered": new_sha}
            side.unlink(missing_ok=True)
        elif entry.get("offered") != new_sha:
            _write(side, data)
            report["conflicts"].append(rel)
            entry["offered"] = new_sha
    for rel in [r for r in files if r not in bundled]:
        dest = d / rel
        if dest.is_file() and _sha(dest.read_bytes()) == files[rel].get("installed"):
            dest.unlink()
            for parent in dest.parents:
                if parent == d:
                    break
                try:
                    parent.rmdir()
                except OSError:
                    break
        (d / (rel + NEW)).unlink(missing_ok=True)
        del files[rel]
    wanted = {"lang": lang, "files": files}
    if json.dumps(wanted, sort_keys=True) != before or not (d / MANIFEST).exists():
        _write(d / MANIFEST, (json.dumps(wanted, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return {"path": str(d), "lang": lang, **report}


def _front_matter(text: str) -> dict[str, str]:
    """只读 name 和 description（各占一行，可带引号）；写得不规范也不报错，列表里只是少一句说明。"""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"(name|description):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def listing(ws: Path) -> list[dict[str, Any]]:
    """工作区里现有的 skill（内置的和用户自己加的）。``update`` = 旁边有等着合并的新版本文件。"""
    d = skills_dir(ws)
    rows = []
    if not d.is_dir():
        return rows
    manifest = _load_manifest(d)["files"]
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        f = sub / "SKILL.md"
        if not f.is_file():
            continue
        front = _front_matter(f.read_text(encoding="utf-8", errors="replace"))
        entry = manifest.get(f"{sub.name}/SKILL.md")
        rows.append({
            "name": sub.name,
            "description": front.get("description", ""),
            "path": str(f),
            "builtin": entry is not None,
            "update": sorted(p.relative_to(d).as_posix()[: -len(NEW)] for p in sub.rglob("*" + NEW)),
        })
    return rows


def unknown_commands(ws: Path, known: set[str]) -> list[dict[str, str]]:
    """skill 里提到、应用已经没有的命令（用户改过的旧版本可能还在用）。``known``：命令、事件、设置项的名字。"""
    d = skills_dir(ws)
    out = []
    if not d.is_dir():
        return out
    for f in sorted(d.rglob("*.md")):
        for name in sorted(set(COMMAND_RE.findall(f.read_text(encoding="utf-8", errors="replace")))):
            if name.split(".")[0] in NOT_COMMANDS or name in known or any(k.startswith(name + "_") for k in known):
                continue
            out.append({"file": f.relative_to(d).as_posix(), "command": name})
    return out
