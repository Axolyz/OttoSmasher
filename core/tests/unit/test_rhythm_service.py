"""节奏与卡拍的 Core 侧（规格 09 §9.3–§9.5、03 §3.3）：新采样的默认参数、节奏视图、全局 BPM、逐采样参数（可撤销、绑定分析版本）、
临时纯 mora 与「写进人工占格」、试听渲染缓存与播放句柄、单音没有卡拍。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core import units
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import dumps, loads
from ottosmasher.core.errors import CoreError
from ottosmasher.core.server import Core
from ottosmasher.media import wavfile

need_rb = pytest.mark.skipif(shutil.which("rubberband") is None, reason="rubberband not installed")
SR = 16000
# 音块：k a（2.1）、k a（2.4）、k a（2.65）、t a（3.0）| 停顿 3.4–4.2 | k a（4.3）、s a（4.6）、k a（5.0）
ONSETS = [2.1, 2.4, 2.65, 3.0, 4.3, 4.6, 5.0]


def phones() -> list[dict]:
    out = []
    for i, o in enumerate(ONSETS):
        out.append({"label": "k", "start": round(o - 0.05, 6), "end": o, "mora": i})
        end = 3.4 if i == 3 else (ONSETS[i + 1] - 0.05 if i + 1 < len(ONSETS) else 5.4)
        out.append({"label": "a", "start": o, "end": round(end, 6), "mora": i, "strength": 1.0})
        if i == 3:
            out.append({"label": "pau", "start": 3.4, "end": 4.25, "mora": None})
    return out


@pytest.fixture
def core(tmp_path: Path):
    t = np.arange(10 * SR) / SR
    x = 0.3 * np.sin(2 * np.pi * 200 * t)
    x[(t >= 3.4) & (t < 4.25)] = 0.0
    wav = tmp_path / "a.wav"
    wavfile.save_wav24(wav, x[:, None].astype(np.float32), SR)
    c = Core(tmp_path / "ws")
    c.open()
    r = c.sources.add([str(wav)])[0]
    c.aid = r["assets"][0]["assetId"]
    c.events = []
    c.rhythm.emit = lambda name, data: c.events.append((name, data))
    yield c
    c.close()


def sample(c, start=2.0, end=5.6, name="s", nature="speech"):
    return c.samples.create(c.aid, start, end, name=name, nature=nature)["id"]


def align(c, owner=None, start=2.0, end=5.6, ph=None):
    """在 [start, end) 上登记一句手输单元的成功分析（所有者 2026-10-08：分析属于文本单元；没有自己文本的采样按范围读到它）。"""
    snap = c.flatten._freeze(c.aid, start, end)["_snap"]
    rid = new_id()
    ph = ph or phones()
    sp = units.span_of({"phones": ph})
    unit = units.typed_id(c.aid, start, end)
    c.conn.execute(
        "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at, span_start, span_end)"
        " VALUES (?, 'alignment', 'asset_text', ?, ?, ?, ?, ?, 'ok', 0, ?, ?, ?, ?)",
        (rid, unit, c.aid, start, end, dumps({"audio": {"snapshot": snap}}),
         dumps({"phones": ph, "morae": ["ka", "ka", "ka", "ta", "ka", "sa", "ka"]}), now_iso(), sp[0], sp[1]),
    )
    c.conn.execute(
        "INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('asset_text', ?, 'alignment', ?, 1)"
        " ON CONFLICT(owner_type, owner_id, kind) DO UPDATE SET run_id=excluded.run_id, version=version+1",
        (unit, rid),
    )
    return rid


def set_setting(c, key, value):
    cur = c.conn.execute("SELECT version FROM setting WHERE key=?", (key,)).fetchone()
    c.edits.apply({"ops": [{"entity": "setting", "id": key, "version": cur[0] if cur else 0, "fields": {"value": value}}]})


def version(c, sid):
    return c.samples.get(sid)["version"]


def test_new_samples_take_setting_defaults_and_old_ones_keep_theirs(core):
    a = sample(core)
    assert loads(core.conn.execute("SELECT rhythm FROM sample WHERE id=?", (a,)).fetchone()[0])["sensitivity"] == 1.0
    set_setting(core, "analysis.pause_sensitivity", 1.5)
    set_setting(core, "analysis.segment_threshold", 0.5)
    b = sample(core)
    rb = loads(core.conn.execute("SELECT rhythm FROM sample WHERE id=?", (b,)).fetchone()[0])
    assert (rb["sensitivity"], rb["segmentThreshold"]) == (1.5, 0.5)
    assert core.rhythm.params_of(core.conn.execute("SELECT * FROM sample WHERE id=?", (a,)).fetchone())["sensitivity"] == 1.0


def test_view_without_analysis_and_with(core):
    s = sample(core)
    v = core.rhythm.view(s)
    assert v["status"] == "none" and v["reason"]["code"] == "rhythm-no-analysis"
    align(core, s)
    v = core.rhythm.view(s)
    assert v["status"] == "ok" and len(v["blocks"]) == 7
    assert [b["text"] for b in v["blocks"]] == ["ka", "ka", "ka", "ta", "ka", "sa", "ka"]
    assert len(v["pauses"]) == 1 and v["pauses"][0] == [pytest.approx(3.42, abs=0.011), pytest.approx(4.23, abs=0.011)]
    assert [c["k"] for c in v["cuts"] if not c["merged"]] == [4] and len(v["segments"]) == 2
    assert v["route"] == "raw" and len(v["cells"]) == 7 and v["bpm"] is None
    nf = v["schemes"]["near_fast"]
    assert nf["speed"] == pytest.approx(1.0, abs=1e-3)  # 原速卡拍
    assert [p["kind"] for p in nf["points"]].count("segment-tail") == 1 and nf["points"][-1]["kind"] == "tail"
    assert v["blocks"][3]["restCells"] >= 1 and v["blocks"][0]["consonants"] == ["k"]
    assert v["blocks"][0]["midi"] is None  # F0 没测 → 未知，不是 0


def test_global_bpm(core):
    s = sample(core)
    align(core, s)
    assert core.rhythm.set_bpm(180) == {"bpm": 180.0}
    assert core.events[-1] == ("rhythm.bpm", {"bpm": 180.0})
    v = core.rhythm.view(s)
    assert v["bpm"] == 180.0 and v["schemes"]["near_fast"]["bpm"] == 180.0 and v["schemes"]["near_fast"]["speed"] >= 1 - 1e-5
    assert v["schemes"]["near_slow"]["speed"] < 1
    with pytest.raises(CoreError) as e:
        core.rhythm.set_bpm(401)
    assert e.value.code == "bpm-invalid"
    core.rhythm.set_bpm(None)
    assert core.rhythm.bpm() is None
    # 不进撤销
    assert core.edits.peek_undo() is None


def test_params_are_undoable_and_bound_to_the_analysis_version(core):
    s = sample(core)
    align(core, s)
    core.rhythm.set_params(s, version(core, s), {"cells": {"0": 3}, "segmentThreshold": 1.0})
    v = core.rhythm.view(s)
    assert v["cells"][0] == 3 and v["blocks"][0]["manual"] and v["manual"]["applied"]
    assert v["segments"] == [] and v["params"]["segmentThreshold"] == 1.0
    core.edits.undo()
    v = core.rhythm.view(s)
    assert not v["blocks"][0]["manual"] and len(v["segments"]) == 2
    core.rhythm.set_params(s, version(core, s), {"cells": {"0": 3}, "merges": [4]})
    assert core.rhythm.view(s)["segments"] == []
    # 新的分析版本：人工项不自动套用，提示属于旧版本；先重新套用或清除
    align(core, s)
    v = core.rhythm.view(s)
    assert v["manual"]["stale"] and not v["manual"]["applied"] and not v["blocks"][0]["manual"]
    with pytest.raises(CoreError) as e:
        core.rhythm.set_params(s, version(core, s), {"cells": {"1": 2}})
    assert e.value.code == "rhythm-manual-stale"
    core.rhythm.set_params(s, version(core, s), {"reapply": True})
    assert core.rhythm.view(s)["blocks"][0]["manual"]
    # 拆点变了：音块序号对不上，人工占格与手动切分/合并一起清掉
    core.rhythm.set_params(s, version(core, s), {"splits": [3]})
    v = core.rhythm.view(s)
    assert v["manual"]["cells"] == {} and v["manual"]["merges"] == [] and v["manual"]["splits"] == [3]
    # 灵敏度越界、乐观并发
    with pytest.raises(CoreError):
        core.rhythm.set_params(s, version(core, s), {"sensitivity": 3})
    with pytest.raises(CoreError) as e:
        core.rhythm.set_params(s, version(core, s) - 1, {"sensitivity": 1.2})
    assert e.value.code == "edit-conflict"


def test_pure_mora_is_temporary_and_can_be_written_into_manual_cells(core):
    s = sample(core)
    align(core, s)
    v = core.rhythm.view(s, mora=True)
    assert v["route"] == "mora" and v["cells"] == [1] * 7
    assert core.rhythm.view(s)["route"] == "raw"  # 不保存
    core.rhythm.set_params(s, version(core, s), {"moraToCells": {"longVowel": False}})
    v = core.rhythm.view(s)
    assert v["route"] == "raw" and v["cells"] == [1] * 7 and all(b["manual"] for b in v["blocks"])
    # 缺 mora：纯 mora 不可用并说明，原节奏照常
    t = sample(core, name="t")
    ph = phones()
    ph[3]["mora"] = None
    align(core, t, ph=ph)
    v = core.rhythm.view(t, mora=True)
    assert v["route"] == "raw" and v["routeError"]["code"] == "rhythm-mora-unavailable" and v["routeError"]["args"]["blocks"] == [1, 2]  # 第 1 块的格数要用第 2 块的首 mora


@need_rb
def test_render_cache_and_playback_handle(core):
    s = sample(core)
    align(core, s)
    core.rhythm.set_bpm(150)
    r = core.rhythm.render(s, "stretched", "voice")
    v = core.rhythm.view(s)
    assert r["plan"] == "near_fast" and r["bpm"] == 150 and r["duration"] == pytest.approx(v["schemes"]["near_fast"]["outSeconds"], abs=1e-3)
    path = core.rhythm.render_dir / f"{r['key']}.wav"
    mt = path.stat().st_mtime_ns
    assert core.rhythm.render(s, "stretched", "voice")["key"] == r["key"] and path.stat().st_mtime_ns == mt  # 复用
    h = core.rhythm.resolve_render(r["key"])
    assert h["path"] == str(path) and h["fileEnd"] == pytest.approx(r["duration"])
    # 换方案 / 声音 → 不同的文件；不卡拍 + 纯咔哒 = 原长
    assert core.rhythm.render(s, "stretched", "voice", "near_slow")["key"] != r["key"]
    c = core.rhythm.render(s, "original", "click")
    assert c["duration"] == pytest.approx(3.6, abs=1e-3) and c["plan"] is None
    pcm, _ = load(core.rhythm.render_dir / f"{c['key']}.wav")
    assert np.abs(pcm[: int(0.09 * SR)]).max() == 0 and np.abs(pcm[int(0.1 * SR) : int(0.11 * SR)]).max() > 0.1  # 第一个起音 2.1 处有咔哒
    with pytest.raises(CoreError) as e:
        core.rhythm.resolve_render("../../etc/passwd")
    assert e.value.code == "rhythm-render-missing"


def load(path):
    from scipy.io import wavfile as sw

    rate, y = sw.read(str(path))
    return y.astype(np.float64) / 2**31 if y.dtype == np.int32 else y, rate


def test_single_sounds_have_no_stretch(core):
    s = sample(core, nature="pitched")
    align(core, s)
    with pytest.raises(CoreError) as e:
        core.rhythm.render(s, "stretched", "voice")
    assert e.value.code == "rhythm-not-for-single-sound"


def test_penalty_change_rebuilds(core):
    s = sample(core)
    align(core, s)
    a = core.rhythm.analysis(s)
    set_setting(core, "analysis.penalty", 0.0)
    b = core.rhythm.analysis(s)
    assert a.identity != b.identity and b.penalty == 0.0
