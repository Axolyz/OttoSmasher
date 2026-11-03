"""按 tools/third_party.json 把第三方文件拉到 third_party/，逐个校验 SHA-256。

用法：.venv/bin/python tools/fetch_third_party.py [--only ID ...]
已存在且 SHA 一致的文件跳过；SHA 不一致一律报错，不覆盖、不将就。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TP = ROOT / "third_party"
DEV_MODELS = ROOT / "dev-workspace" / "Models"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def this_platform() -> str:
    machine = platform.machine().lower()
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{sys.platform if sys.platform != 'win32' else 'win32'}-{machine}"


def download(url: str, dest: Path, want: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        print(f"  下载 {url}")
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — 固定的 https 地址
            shutil.copyfileobj(resp, tmp)
    got = sha256(Path(tmp.name))
    if got != want:
        Path(tmp.name).unlink()
        raise SystemExit(f"SHA-256 不一致：{url}\n  期望 {want}\n  实际 {got}")
    Path(tmp.name).replace(dest)


def ensure_file(f: dict, base: Path) -> None:
    dest = base / f["dest"]
    if dest.exists() and sha256(dest) == f["sha256"]:
        print(f"  已就位 {f['dest']}")
        return
    if dest.exists():
        raise SystemExit(f"已存在但 SHA-256 不一致，请人工检查：{dest}")
    local = f.get("local")
    if local and (DEV_MODELS / local).exists() and sha256(DEV_MODELS / local) == f["sha256"]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEV_MODELS / local, dest)
        print(f"  复制 {local}（SHA 一致）")
        return
    download(f["url"], dest, f["sha256"])


def ensure_archive(item: dict) -> None:
    dest = TP / item["dest"]
    marker = dest / ".sha256"
    if marker.exists() and marker.read_text().strip() == item["sha256"]:
        print(f"  已就位 {item['dest']}")
        return
    archive = TP / "downloads" / item["url"].rsplit("/", 1)[1]
    if not (archive.exists() and sha256(archive) == item["sha256"]):
        download(item["url"], archive, item["sha256"])
    if archive.stat().st_size != item["size"]:
        raise SystemExit(f"大小不一致：{archive}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    strip = int(item.get("strip_components", 0))
    with tarfile.open(archive) as tf:
        for m in tf.getmembers():
            parts = Path(m.name).parts[strip:]
            if not parts:
                continue
            if m.issym() or m.islnk() or ".." in parts:
                raise SystemExit(f"压缩包里有不允许的条目：{m.name}")
            m.name = str(Path(*parts))
            tf.extract(m, dest, filter="data")
    marker.write_text(item["sha256"])
    print(f"  解压到 {item['dest']}")


def main() -> int:
    # Windows 控制台的默认编码不一定能写中文（cp1252 直接报错）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    manifest = json.loads((ROOT / "tools" / "third_party.json").read_text(encoding="utf-8"))
    plat = this_platform()
    for item in manifest["items"]:
        if args.only and item["id"] not in args.only:
            continue
        if "*" not in item["platforms"] and plat not in item["platforms"]:
            continue
        print(f"[{item['id']}]")
        if item["kind"] == "archive":
            ensure_archive(item)
        else:
            for f in item["files"]:
                ensure_file(f, TP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
