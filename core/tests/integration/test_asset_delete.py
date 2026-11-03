"""删除音轨（所有者 2026-11-03）：原混音不能删；有采样在用的不让删；没人用的列出来；默认轨删除后没有默认轨，不自动换。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from test_core_process import CoreProc


def _wav(path: Path, freq: int = 330) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={freq}:sample_rate=48000:duration=2", str(path)], check=True)
    return path


def test_delete_rules(tmp_path: Path):
    c = CoreProc(tmp_path / "ws")
    try:
        sid = c.call("sources.add", paths=[str(_wav(tmp_path / "ep1.wav"))])["r"][0]["sourceId"]
        stream = next(a for a in c.call("assets.listForSource", sourceId=sid)["r"] if a["origin"] == "stream")
        stems = tmp_path / "stems"
        stems.mkdir()
        used = c.call("dev.registerStem", sourceId=sid, path=str(_wav(stems / "m_Vocals.wav", 440)))["r"]["assetId"]
        spare = c.call("dev.registerStem", sourceId=sid, path=str(_wav(stems / "m_Other.wav", 441)))["r"]["assetId"]
        default = c.call("dev.registerStem", sourceId=sid, path=str(_wav(stems / "n_Vocals.wav", 442)))["r"]["assetId"]
        assert c.call("samples.create", assetId=used, start=0.2, end=0.8, name="x", nature="speech")["ok"]
        assert c.call("tracks.setDefault", sourceId=sid, role="vocal", assetId=default)["ok"]

        pv = c.call("assets.deletePreview", id=stream["id"])["r"]
        assert (pv["deletable"], pv["reason"]) == (False, "asset-stream")
        pv = c.call("assets.deletePreview", id=used)["r"]
        assert (pv["deletable"], pv["reason"], pv["samples"]) == (False, "asset-samples", 1)
        pv = c.call("assets.deletePreview", id=default)["r"]
        assert pv["deletable"] and pv["defaults"] == ["vocal"]

        # 没人用的：不含有采样的、默认轨、原混音
        assert [u["assetId"] for u in c.call("assets.unused")["r"]] == [spare]

        # 整批里有一条不能删 → 全部不动
        r = c.call("assets.delete", ids=[spare, used])
        assert not r["ok"] and r["e"]["code"] == "asset-not-deletable" and r["e"]["args"]["id"] == used
        assert [u["assetId"] for u in c.call("assets.unused")["r"]] == [spare]

        assert c.call("assets.delete", ids=[spare])["r"]["deleted"] == 1
        assert c.call("assets.unused")["r"] == []
        assert (stems / "m_Other.wav").exists()  # 外部文件只删记录

        # 删默认轨：没有默认轨了，不自动换一条
        assert c.call("assets.delete", ids=[default])["r"]["deleted"] == 1
        assert c.call("assets.tracks", sourceId=sid)["r"]["defaults"].get("vocal") is None
        assert c.call("assets.get", id=used)["r"]["id"] == used  # 有采样的那条还在
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=30)
