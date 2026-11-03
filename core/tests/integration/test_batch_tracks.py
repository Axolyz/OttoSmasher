"""批量把分离出的人声设为默认人声轨（所有者 2026-11-03）：用户明确点才设；一次编辑，一次撤销。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from test_core_process import CoreProc


def _wav(path: Path, freq: int = 330) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={freq}:sample_rate=48000:duration=2", str(path)], check=True)
    return path


def test_default_vocal_from_separation(tmp_path: Path):
    c = CoreProc(tmp_path / "ws")
    try:
        a, b, plain = (c.call("sources.add", paths=[str(_wav(tmp_path / f"{n}.wav"))])["r"][0]["sourceId"] for n in ("ep1", "ep2", "ep3"))
        stems = tmp_path / "stems"
        stems.mkdir()
        va = c.call("dev.registerStem", sourceId=a, path=str(_wav(stems / "modelx_Vocals.wav", 440)))["r"]["assetId"]
        c.call("dev.registerStem", sourceId=b, path=str(_wav(stems / "modely_Vocals.wav", 441)))
        # dev.registerStem 记的 production 里有模型名；同一个声部名、不同模型分开列
        got = c.call("tracks.separatedVocals", sourceIds=[a, b, plain])["r"]
        assert {(x["model"], x["stem"], x["sources"]) for x in got} == {("modelx", "Vocals", 1), ("modely", "Vocals", 1)}

        r = c.call("tracks.defaultFromSeparation", sourceIds=[a, b, plain], model="modelx", stem="Vocals")["r"]
        assert r["applied"] == 1 and r["skipped"] == 2 and r["edit_id"]
        assert c.call("assets.tracks", sourceId=a)["r"]["defaults"]["vocal"] == va
        assert c.call("assets.tracks", sourceId=b)["r"]["defaults"].get("vocal") is None  # 没有这个模型的不动，不回退混音

        again = c.call("tracks.defaultFromSeparation", sourceIds=[a], model="modelx", stem="Vocals")["r"]
        assert again == {"edit_id": None, "applied": 0, "skipped": 1}  # 已经是它：不产生新的编辑
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=30)
