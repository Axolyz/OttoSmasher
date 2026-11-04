"""卡拍导出与 REAPER 交接（规格 12 §12.1、§12.3、16 R21.4、R21.7）。"""

from __future__ import annotations

from pathlib import Path
import json
import shutil

import numpy as np
import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.domain import reaper
from ottosmasher.domain.mapping import Mapping
from ottosmasher.core import settings as settings_mod
from ottosmasher.media import wavfile

from test_rhythm_service import SR, align, core, sample  # noqa: F401 — 同一组合成素材

need_rb = pytest.mark.skipif(shutil.which("rubberband") is None, reason="rubberband not installed")
WORDS = {"original": "原混音", "vocal": "人声", "stretch": "卡拍"}


# ---------------------------------------------------------------- 清单的两层映射（R21.4）


def test_manifest_composes_two_mappings():
    asset = Mapping.of([[0, 10], [0.4, 10.8], [1, 11.4]])
    stretch = Mapping.of([[0, 0], [0.5, 0.4], [1, 1]])  # 卡拍输出秒 → 资产局部秒
    assert asset.compose(stretch).to_list() == [[0, 10], [0.5, 10.8], [1, 11.4]]


# ---------------------------------------------------------------- 剪贴板格式（R21.7）


def item(path="/tmp/a.wav", markers=((0.0, 0.0), (0.5, 0.4), (1.0, 1.0)), name="やったー"):
    return reaper.Item(0.0, 0.25, 1.0, 0.5, name, list(markers), path)


def test_clipboard_format():
    text = reaper.clipboard([item()], guid=lambda: "{G}")
    assert text.startswith("<ITEM\0") and text.endswith(">\0>\0\0")
    lines = text.rstrip("\0").split("\0")
    assert "PLAYRATE 1 1 0 -1 0 0.0025" in lines
    # 只写秒，不写节拍位置：REAPER 会按工程速度和这个节拍数的比例缩放条目（所有者 2026-11-04：rate 变成 1.3～1.5）
    assert "SNAPOFFS 0.250000000000" in lines and "LENGTH 1.000000000000" in lines and "POSITION 0.000000000000" in lines
    sm = next(ln for ln in lines if ln.startswith("SM "))
    assert sm == "SM 0.000000000000 0.000000000000 + 0.500000000000 0.400000000000 + 1.000000000000 1.000000000000"
    assert 'FILE "/tmp/a.wav"' in lines and 'NAME "やったー"' in lines
    assert "\n" not in text
    assert reaper.template([item()], guid=lambda: "{G}").splitlines()[0] == "<ITEM"


def test_quote_choice_and_rejections():
    lines = reaper.item_lines(item(path='/tmp/a "b".wav'), guid=lambda: "{G}")
    assert "FILE '/tmp/a \"b\".wav'" in lines
    lines = reaper.item_lines(item(path="/tmp/a\"b'c.wav"), guid=lambda: "{G}")
    assert "FILE `/tmp/a\"b'c.wav`" in lines
    for bad in ("/tmp/a\nb.wav", "/tmp/a\"'`.wav"):
        with pytest.raises(CoreError) as e:
            reaper.item_lines(item(path=bad))
        assert e.value.code == "reaper-path-invalid"
    with pytest.raises(CoreError) as e:
        reaper.item_lines(item(markers=((0, 0), (0.5, 0.6), (0.6, 0.5))))
    assert e.value.code == "reaper-markers-not-monotonic"


def test_batch_lays_items_out_one_bar_apart():
    assert reaper.lay_out([1.0, 2.0, 0.5], [0.5, 0.25, 0.5]) == [0.0, 3.0, 6.0]


# ---------------------------------------------------------------- 经 Core


@need_rb
def test_stretched_export_and_manifest(core):  # noqa: F811
    s = sample(core)
    align(core, s)
    core.rhythm.set_bpm(120)
    r = core.handoff.export_stretched(s, WORDS)
    name = Path(r["path"]).name
    assert "__卡拍-120BPM__" in name and name.startswith("s__") and name.endswith(".wav")
    v = core.rhythm.view(s)
    rate, ch, bits, frames = wavfile.info(r["path"])
    assert (rate, bits) == (SR, 24) and frames / rate == pytest.approx(v["schemes"]["near_fast"]["outSeconds"], abs=1e-3)
    man = json.loads((core.ws.data / "Manifests" / f"{r['key'][:24]}.json").read_text(encoding="utf-8"))
    assert man["scheme"]["bpm"] == 120 and man["mapping"][0] == [0.0, pytest.approx(2.0)]
    assert man["mapping"][-1][1] == pytest.approx(5.6) and man["mapping"][-1][0] == pytest.approx(frames / rate)
    # 同一请求复用；拖出跟随版本
    assert r["mapping"] == man["mapping"] and r["frames"] == frames and r["sampleRate"] == rate  # 返回里就有合成映射
    again = core.handoff.export_stretched(s, WORDS)
    assert again["reused"] is True and again["mapping"] == man["mapping"] and again["frames"] == frames
    paths = core.handoff.export_samples([s], WORDS, {s: "stretched"})
    assert paths == [r["path"]]
    orig = core.handoff.export_samples([s], WORDS)
    assert "卡拍" not in orig[0]
    # 单音没有卡拍导出
    p = sample(core, nature="pitched", name="p")
    align(core, p)
    with pytest.raises(CoreError):
        core.handoff.export_stretched(p, WORDS)


@need_rb
def test_reaper_handoff_original_file_markers_and_batch(core):  # noqa: F811
    a = sample(core, name="a")
    b = sample(core, name="b")
    align(core, a)
    align(core, b)
    core.rhythm.set_bpm(150)
    h = core.handoff.reaper_handoff([a], WORDS, kind="fitted")
    lines = h["clipboard"].rstrip("\0").split("\0")
    assert lines[0] == "<ITEM" and h["clipboard"].endswith("\0\0")
    f = h["files"][0]
    assert "REAPER" in Path(f).parts and Path(f).name.startswith("a__原混音__")
    # 原声没有烘焙：等于采样范围的原始样本
    _rate, _ch, _bits, frames = wavfile.info(f)
    assert frames == round(3.6 * SR)
    sm = next(ln for ln in lines if ln.startswith("SM ")).removeprefix("SM ").split(" + ")
    pts = [(float(x.split()[0]), float(x.split()[1])) for x in sm]
    assert all(t1 > t0 and s1 > s0 for (t0, s0), (t1, s1) in zip(pts, pts[1:]))
    v = core.rhythm.view(a)
    onsets_src = [round(p["src"] - 2.0, 6) for p in v["schemes"]["near_fast"]["points"] if p["kind"] == "onset"]
    for o in onsets_src:  # 每个起音都有标记
        assert any(abs(s_ - o) < 1.5 / SR for _t, s_ in pts)
    snap = next(ln for ln in lines if ln.startswith("SNAPOFFS")).split()
    first = next(p for p in v["schemes"]["near_fast"]["points"] if p["kind"] == "onset")
    assert len(snap) == 2 and float(snap[1]) == pytest.approx(first["tgt"], abs=1 / SR)
    assert (core.ws.library / "REAPER").exists() and h["manifest"].endswith(".json")
    # 再交接一次：同名同内容复用文件
    assert core.handoff.reaper_handoff([a], WORDS, kind="fitted")["files"] == [f]
    # 批量依次排开、间隔一小节
    hb = core.handoff.reaper_handoff([a, b], WORDS, kind="fitted")
    blocks = hb["clipboard"].rstrip("\0").split("\0")
    pos = [float(ln.split()[1]) for ln in blocks if ln.startswith("POSITION")]
    lens = [float(ln.split()[1]) for ln in blocks if ln.startswith("LENGTH")]
    assert pos[0] == 0 and pos[1] == pytest.approx(lens[0] + 4 * 60 / 150, abs=1e-9)
    t = core.handoff.reaper_template([a], WORDS, kind="fitted")
    assert t["path"].endswith(".RTrackTemplate") and open(t["path"], encoding="utf-8").read().startswith("<ITEM\n")
    # 同名但内容不同 → 报错
    with open(f, "r+b") as fh:
        fh.seek(-4, 2)
        fh.write(b"\x01\x02\x03\x04")
    with pytest.raises(CoreError) as e:
        core.handoff.reaper_handoff([a], WORDS, kind="fitted")
    assert e.value.code == "reaper-file-conflict"


@need_rb
def test_reaper_snap_setting(core):  # noqa: F811
    from test_rhythm_service import set_setting

    s = sample(core)
    align(core, s)
    set_setting(core, "export.reaper_snap", "start")
    lines = core.handoff.reaper_handoff([s], WORDS)["clipboard"].split("\0")
    assert "SNAPOFFS 0.000000000000" in lines


@need_rb
def test_drag_reuses_the_audition_render(core, monkeypatch):  # noqa: F811
    s = sample(core)
    align(core, s)
    core.rhythm.set_bpm(150)
    core.rhythm.render(s, "stretched", "voice")  # 先试听一次卡拍
    from ottosmasher.media import stretch as render_mod

    def boom(*a, **k):
        raise AssertionError("should reuse the audition render")

    monkeypatch.setattr(render_mod, "render", boom)
    # 拖出 / 导出卡拍：直接用试听渲染的结果
    assert core.handoff.export_stretched(s, WORDS)["path"]


def _markers(clip):
    lines = clip.rstrip("\0").split("\0")
    sm = next(ln for ln in lines if ln.startswith("SM ")).removeprefix("SM ").split(" + ")
    length = float(next(ln for ln in lines if ln.startswith("LENGTH")).split()[1])
    return [(float(x.split()[0]), float(x.split()[1])) for x in sm], length


@need_rb
def test_reaper_two_kinds_share_the_original_audio(core):  # noqa: F811
    """所有者 2026-11-04：original = 未卡拍的原声，音头有 1 倍速标记；fitted = 同一份原声，标记把它卡好；删掉标记就回到前者。"""
    s = sample(core)
    align(core, s)
    core.rhythm.set_bpm(150)
    original = core.handoff.reaper_handoff([s], WORDS, kind="original")
    fitted = core.handoff.reaper_handoff([s], WORDS, kind="fitted")
    assert original["files"] == fitted["files"] and "卡拍" not in original["files"][0]
    _rate, _ch, _bits, frames = wavfile.info(original["files"][0])

    pts, length = _markers(original["clipboard"])
    assert all(t == src for t, src in pts)
    assert pts[0][0] == 0 and abs(pts[-1][0] - frames / SR) < 1e-9 and abs(length - frames / SR) < 1e-9
    v = core.rhythm.view(s)
    start = core.conn.execute("SELECT start FROM sample WHERE id=?", (s,)).fetchone()[0]
    onsets = [p["src"] - start for p in v["schemes"]["near_fast"]["points"] if p["kind"] == "onset"]
    assert onsets
    for o in onsets:  # 标记在原声里的音头上，不是卡拍后的位置
        assert any(abs(t - o) < 1.5 / SR for t, _src in pts)

    pts, _length = _markers(fitted["clipboard"])
    assert any(abs(t - src) > 1e-6 for t, src in pts)  # 有非 1 倍速的段
    for o in onsets:
        assert any(abs(src - o) < 1.5 / SR for _t, src in pts)


@need_rb
def test_reaper_default_kind_follows_setting(core):  # noqa: F811
    from test_rhythm_service import set_setting

    s = sample(core)
    align(core, s)
    core.rhythm.set_bpm(150)
    pts, _ = _markers(core.handoff.reaper_handoff([s], WORDS)["clipboard"])
    assert any(abs(t - src) > 1e-6 for t, src in pts)  # 默认：卡拍效果
    set_setting(core, "export.reaper_kind", "original")
    pts, _ = _markers(core.handoff.reaper_handoff([s], WORDS)["clipboard"])
    assert all(t == src for t, src in pts)


@need_rb
def test_reaper_kind_old_stored_values_read_as_fitted(core):  # noqa: F811
    for old in ("baked", "unbaked"):
        core.conn.execute("INSERT OR REPLACE INTO setting(key, value, version, updated_at) VALUES ('export.reaper_kind', ?, 1, '')", (f'"{old}"',))
        assert settings_mod.values(core.conn)["export.reaper_kind"] == "fitted"


@need_rb
def test_stretched_video_synced_and_original_speed(core, tmp_path):  # noqa: F811
    """S7.2：卡拍版两种画面——同映射变速（时长 = 卡拍音频）/ 原速画面（时长 = 原声，另存卡拍 WAV）。"""
    import subprocess

    from ottosmasher.core import visuals
    from ottosmasher.core.video_export import run_job

    s = sample(core)
    align(core, s)
    core.rhythm.set_bpm(120)
    png = tmp_path / "pic.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x36:d=0.1", "-frames:v", "1", str(png)], check=True)
    vb = visuals.prepare(core.conn, "sample", s, str(png))
    core.edits.apply({"ops": [{"entity": "sample", "id": s, "version": core.samples.get(s)["version"], "fields": {"visual_binding_id": vb}}]})
    out = core.video_export.sample(s, version="stretched", picture="synced", words=WORDS)
    job = core.conn.execute("SELECT params FROM job WHERE id = ?", (out["job"]["id"],)).fetchone()[0]
    params = json.loads(job)
    v = core.rhythm.view(s)
    assert params["duration"] == pytest.approx(v["schemes"]["near_fast"]["outSeconds"], abs=1e-3)
    assert params["frames"] == round(params["duration"] * 30)  # 图片：30 fps
    res = run_job(params, type("C", (), {"progress": lambda *a, **k: None})())
    core.video_export._adopt({"id": "job-1", "params": job}, res)
    assert "卡拍-120BPM" in params["target"] and params["target"].endswith(".mp4")
    assert res["path"] == params["target"] and res["fps"] == params["fps"]  # 成品路径记进任务结果（事后按任务查）
    orig = core.video_export.sample(s, version="stretched", picture="original", words=WORDS)
    p2 = json.loads(core.conn.execute("SELECT params FROM job WHERE id = ?", (orig["job"]["id"],)).fetchone()[0])
    assert p2["duration"] == pytest.approx(3.6) and orig["stretchedWav"].endswith(".wav")
