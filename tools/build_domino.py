"""编译 pydomino 的 tokenizer + Viterbi 解码扩展（规格 14 §14.3；macOS arm64 与 Windows x64 都要能构建）。

用法：tools/uv run --with setuptools python tools/build_domino.py
源码：core/native/domino_ext.cpp（绑定）+ third_party/pydomino/src（上游 @4930396，先运行 tools/fetch_third_party.py --only pydomino-src）。
产物：third_party/native/<平台>/_domino<扩展名>（core/ottosmasher/models/domino.py 从这里加载）。
macOS：命令行工具里可能有与链接器不匹配的测试版 SDK，只给本次编译挑一个正式版 SDK（与 tools/build-native.mjs 相同的做法）。
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
import sysconfig
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "third_party" / "pydomino" / "src"
BINDING = ROOT / "core" / "native" / "domino_ext.cpp"


def platform_tag() -> str:
    machine = platform.machine().lower()
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{sys.platform}-{machine}"


def pick_sdk() -> None:
    if sys.platform != "darwin" or os.environ.get("SDKROOT"):
        return
    base = Path("/Library/Developer/CommandLineTools/SDKs")
    if not base.is_dir():
        return
    stable = []
    for p in base.iterdir():
        m = re.fullmatch(r"MacOSX(\d+)\.(\d+)\.sdk", p.name)
        if m:
            stable.append(((int(m[1]), int(m[2])), p))
    # 测试版通常比正式版高一个大版本；取次高的大版本里最新的（只有一个大版本时就用它）
    majors = sorted({v[0] for v, _ in stable})
    if len(majors) >= 2:
        stable = [x for x in stable if x[0][0] < majors[-1]]
    if stable:
        os.environ["SDKROOT"] = str(max(stable)[1])


def main() -> int:
    missing = [n for n in ("phoneme_transition.cpp", "viterbi.cpp", "phoneme_transitions.txt") if not (UPSTREAM / n).exists()]
    if missing:
        raise SystemExit(f"missing upstream sources {missing}; run: .venv/bin/python tools/fetch_third_party.py --only pydomino-src")
    from setuptools import Extension
    from setuptools.dist import Distribution

    pick_sdk()
    if sys.platform == "win32":
        args = ["/std:c++17", "/O2", "/EHsc", "/utf-8"]
    else:
        args = ["-std=c++17", "-O2"]
    ext = Extension(
        "_domino",
        sources=[str(BINDING), str(UPSTREAM / "phoneme_transition.cpp"), str(UPSTREAM / "viterbi.cpp")],
        include_dirs=[str(UPSTREAM)],
        extra_compile_args=args,
        language="c++",
    )
    out = ROOT / "third_party" / "native" / platform_tag()
    with tempfile.TemporaryDirectory(dir=ROOT / "third_party") as tmp:
        dist = Distribution({"name": "domino", "ext_modules": [ext]})
        cmd = dist.get_command_obj("build_ext")
        cmd.build_lib = str(Path(tmp) / "lib")
        cmd.build_temp = str(Path(tmp) / "temp")
        cmd.ensure_finalized()
        cmd.run()
        built = next(Path(cmd.build_lib).glob("_domino*"))
        out.mkdir(parents=True, exist_ok=True)
        target = out / built.name
        shutil.copy2(built, target)
    print(f"built {target.relative_to(ROOT)} (python {sysconfig.get_python_version()}{', SDK ' + os.environ['SDKROOT'] if os.environ.get('SDKROOT') else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
