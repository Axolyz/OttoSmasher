"""外部回导（规格 06 §6.7、16 S8、R3.7–R3.8）：起点 = 选区起点、终点按文件时长；采样率可不同；越界拒绝不新增；复制进素材库保持原格式；
新资产继承角色、新采样在原选区的派生范围里；删掉原文件后新采样仍可用。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.exports import ExportService, export_samples
from ottosmasher.core.reimport import ReimportService
from ottosmasher.core.samples import SampleService
from ottosmasher.core.sources import SourceService
from ottosmasher.media import decode as dec
from ottosmasher.media import wavfile

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


@pytest.fixture
def env(db, ws, tmp_path):
    src = tmp_path / "ep.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:sample_rate=44100:duration=10", str(src)], check=True)
    [r] = SourceService(db, workspace_root=ws.root).add([str(src)])
    aid = assets_mod.list_for_source(db, r["sourceId"])[0]["id"]
    EditService(db).apply({"ops": [{"entity": "asset", "id": aid, "version": 1, "fields": {"roles": ["vocal"]}}]})
    samples = SampleService(db)
    return ReimportService(db, ws, samples), samples, aid, r["sourceId"]


def test_reimport_positive_and_cleanup(env, db, ws, tmp_path) -> None:
    svc, samples, aid, src = env
    first = samples.create(aid, 4.0, 5.0, name="親")["id"]
    f = tmp_path / "歳納京子！ · G♯5__8ca511050f35.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=830:sample_rate=48000:duration=0.627", str(f)], check=True)
    pv = svc.preview(aid, 4.0, str(f))
    assert pv["ok"] and pv["duration"] == pytest.approx(0.627, abs=1e-3) and pv["end"] == pytest.approx(4.627, abs=1e-3)
    assert pv["suggestedName"]  # 建议名 = 落到的那段的建议名（没有文本层 → 原素材名 起–止）
    out = svc.commit(aid, 4.0, str(f), name="やったー！", local_tags=["project:dil"])
    assert [(t["tag"], t["provenance"]) for t in out["tags"] if t["tag"].startswith("project:")] == [("project:dil", "local")]
    assert out["nature"] == "unclassified" and out["created_via"] == "reimport" and "parent_sample_id" not in out
    assert out["source_start"] == pytest.approx(4.0) and out["duration"] == pytest.approx(0.627, abs=1e-3)
    assert out["source_end"] == pytest.approx(4.627, abs=1e-3)
    new = assets_mod.get(db, out["asset_id"])
    assert new["origin"] == "reimport" and new["roles"] == ["vocal"]  # 继承角色
    assert new["reimport_id"] == new["id"] and new["from_separation"] == 0  # 音素另算一份（所有者 2026-10-12）
    # 返回原素材换到回导到的整轨；它与原选区上的采样互为相关采样（原素材时间交叠）
    assert out["back_asset_id"] == aid
    assert [r["sample"]["id"] for r in samples.related(out["id"])["rows"]] == [first]
    mf = db.execute("SELECT path, location, format FROM media_file WHERE id = ?", (new["media_file_id"],)).fetchone()
    assert mf["location"] == "library" and mf["path"].endswith(".wav") and "/Reimport/" in mf["path"]  # 保持原格式
    f.unlink()  # 删掉用户的原文件：新采样照常可用
    ref, win, media = assets_mod.locate(db, ws.root, new, 0.0, 0.5)
    pcm = dec.decode_frames(ref, 0, 4800, cache=ws.data / "Cache")
    assert ref.sample_rate == 48000 and np.abs(pcm).max() > 0.05
    assert ExportService(db, ws).export_wav(out["asset_id"], 0.0, 0.5, content="x", track="回导")["path"].endswith(".wav")


def test_export_full_reimport_with_rounded_duration(env, db, ws, tmp_path) -> None:
    svc, _, aid, _ = env
    path = tmp_path / "one-beat.wav"
    rate, frames = 44100, 14700
    wavfile.save_wav24(path, np.full((frames, 1), 0.25, dtype=np.float32), rate)
    sample = svc.commit(aid, 4.0, str(path), name="one beat")
    assert sample["duration"] == 0.333333

    exports = ExportService(db, ws)
    [exported] = export_samples(exports, [sample["id"]], {})
    assert wavfile.info(Path(exported)) == (rate, 1, 24, frames)
    assert export_samples(exports, [sample["id"]], {}) == [exported]


def test_reimport_out_of_bounds_rejected(env, db, tmp_path) -> None:
    svc, samples, aid, _src = env
    long = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=sample_rate=44100:duration=8", str(long)], check=True)
    pv = svc.preview(aid, 5.0, str(long))
    assert not pv["ok"] and pv["reason"] == "out-of-bounds"
    n = db.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    with pytest.raises(CoreError) as ei:
        svc.commit(aid, 5.0, str(long))
    assert ei.value.code == "reimport-out-of-bounds"
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == n  # 不新增
