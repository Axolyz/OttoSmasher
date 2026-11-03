"""原片登记、探测、快照、重新定位、删除：规格 16 R1.1、R1.3–R1.5，05 §5.1，04 §4.5。

用 ffmpeg 现场合成小媒体文件（不用 fixtures 里的版权素材）。
"""

import os
import shutil
import sqlite3
import subprocess
import time
import unicodedata
from pathlib import Path

import pytest

from conftest import make_sample
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.sources import SourceService, path_key
from ottosmasher.media import probe as probe_mod

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe not on PATH")


def ff(*args: str) -> None:
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True)


def two_audio_mkv(path: Path, seconds: float = 2.5) -> Path:
    """视频 + 两条 FLAC：第一条英语、第二条日语（带标题）。"""
    ff(
        "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=2",
        "-f", "lavfi", "-i", f"sine=f=220:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=f=880:sample_rate=44100:duration={seconds}",
        "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-c:a", "flac",
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=jpn", "-metadata:s:a:1", "title=Commentary",
        str(path),
    )  # fmt: skip
    return path


def mp3_with_cover(path: Path) -> Path:
    cover = path.with_suffix(".png")
    ff("-f", "lavfi", "-i", "testsrc=size=64x64:rate=1:duration=1", "-frames:v", "1", str(cover))
    ff(
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=44100:duration=1.5", "-i", str(cover),
        "-map", "0", "-map", "1", "-c:a", "libmp3lame", "-q:a", "0", "-c:v", "png",
        "-disposition:v", "attached_pic", str(path),
    )  # fmt: skip
    cover.unlink()
    return path


def wav(path: Path, seconds: float = 1.0, rate: int = 48000) -> Path:
    ff("-f", "lavfi", "-i", f"sine=f=330:sample_rate={rate}:duration={seconds}", "-c:a", "pcm_s24le", str(path))
    return path


@pytest.fixture
def svc(db: sqlite3.Connection, ws) -> SourceService:
    return SourceService(db, workspace_root=ws.root)


@pytest.fixture
def media(tmp_path: Path) -> Path:
    d = tmp_path / "素材 [media] ♪"
    d.mkdir()
    return d


# ---------------------------------------------------------------- 探测（不需要 ffmpeg）


def test_parse_durations_and_languages():
    data = {
        "format": {"format_name": "mov,mp4", "duration": "10.0"},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "duration_ts": 240240, "time_base": "1/24000"},
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2,
             "duration": "9.98", "tags": {"language": "und"}},
            {"index": 2, "codec_type": "audio", "codec_name": "flac", "tags": {"DURATION": "00:23:40.010000000", "LANGUAGE": "jpn"}},
            {"index": 3, "codec_type": "subtitle", "codec_name": "ass"},
            {"index": 4, "codec_type": "audio", "codec_name": "opus"},
        ],
    }  # fmt: skip
    pr = probe_mod.parse(data)
    assert [s.ordinal for s in pr.audio] == [0, 1, 2]
    assert pr.video[0].duration == pytest.approx(10.01)
    assert pr.audio[0].language is None  # und = 未知
    assert pr.audio[1].language == "jpn"
    assert pr.audio[1].duration == pytest.approx(1420.01)
    assert pr.audio[2].duration is None  # 未知就是未知，不拿容器时长冒充


@needs_ffmpeg
def test_packet_duration_when_stream_has_no_duration(media):
    # 有的片源（KF08）流上没有任何时长信息：扫描包时间戳得到时长
    f = two_audio_mkv(media / "p.mkv", seconds=2.5)
    pr = probe_mod.probe(f)
    s = pr.audio[1]
    assert probe_mod.packet_duration(f, s) == pytest.approx(2.5, abs=0.03)
    assert probe_mod.packet_duration(f, pr.video[0]) == pytest.approx(2.0, abs=0.05)


# ---------------------------------------------------------------- 登记


@needs_ffmpeg
def test_duration_is_exact_sample_count(svc, db, media):
    # 时长 = 解码出的确切样本数 / 采样率（容器时长标签不精确；真实素材 YY2-07-A 差 40 个样本）
    f = wav(media / "odd.wav", seconds=1.2345, rate=44100)
    [r] = svc.add([str(f)])
    a = db.execute("SELECT duration FROM sound_asset WHERE source_id=?", (r["sourceId"],)).fetchone()[0]
    assert a * 44100 == round(1.2345 * 44100)
    src = svc.get(r["sourceId"])
    assert src["duration"] == a


@needs_ffmpeg
def test_register_streams_and_defaults(svc, media):
    f = two_audio_mkv(media / "[Group] Some Title [03][1080p].mkv")
    (media / "[Group] Some Title [03][1080p].ass").write_text("[Script Info]\n", encoding="utf-8")
    (media / "[Group] Some Title [03][1080p].srt").write_text("1\n", encoding="utf-8")
    [r] = svc.add([str(f)])
    assert r["ok"] and not r["existing"]
    assert (r["work"], r["episode"], r["inferRule"]) == ("Some Title", "03", 0)
    src = svc.get(r["sourceId"])
    assert src["duration"] == pytest.approx(2.5)
    assert src["default_audio_stream"] == 1  # 日语那条
    assert src["subtitle_path"].endswith(".srt")  # 两种都有时取 .srt（所有者 2026-10-07；只关联，不导入）
    audio = [s for s in src["streams"] if s["kind"] == "audio"]
    assert [(s["ordinal"], s["language"], s["sample_rate"], s["title"]) for s in audio] == [
        (0, "eng", 48000, None),
        (1, "jpn", 44100, "Commentary"),
    ]
    assert src["file_snapshot"]["size"] == f.stat().st_size


@needs_ffmpeg
def test_cover_art_is_not_video_and_first_stream_default(svc, media):
    f = mp3_with_cover(media / "cover ♯.mp3")
    [r] = svc.add([str(f)])
    src = svc.get(r["sourceId"])
    video = [s for s in src["streams"] if s["kind"] == "video"]
    assert len(video) == 1 and video[0]["is_attached_pic"] is True
    assert src["default_audio_stream"] == 0  # 没有日语 → 第一条
    assert (r["work"], r["episode"]) == (None, "cover ♯")  # 作品推断不出 → 未知；素材标识 = 文件名（所有者 2026-10-10）
    assert src["work"] == "" and src["episode"] == "cover ♯"


# R1.5 文件名含空格、方括号、日文、中文、♪、♯ 均可登记
@needs_ffmpeg
@pytest.mark.parametrize("name", ["a b [c] 日本語 中文 ♪ ♯.wav", "（全角）【括号】.wav"])
def test_awkward_names(svc, media, name):
    [r] = svc.add([str(wav(media / name))])
    assert r["ok"], r
    assert svc.get(r["sourceId"])["path"].endswith(name)


@needs_ffmpeg
def test_no_audio_and_missing_file(svc, media):
    v = media / "noaudio.mp4"
    ff("-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=1", "-c:v", "libx264", str(v))
    bad = media / "not media.mkv"
    bad.write_bytes(b"\x00" * 100)
    res = svc.add([str(v), str(media / "gone.wav"), str(bad), str(wav(media / "ok.wav"))])
    assert [x["ok"] for x in res] == [False, False, False, True]  # 每个文件单独成败
    assert [x["error"]["code"] for x in res[:3]] == ["source-no-audio", "file-missing", "media-probe-failed"]
    assert svc.conn.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 1


# R1.1 同一路径重复登记返回已有原片并保留用户设置
@needs_ffmpeg
def test_same_path_returns_existing_and_keeps_user_settings(svc, db, media):
    f = wav(media / "[Kemono Friends][01].wav")
    [r] = svc.add([str(f)])
    EditService(db).apply(
        {"ops": [{"entity": "source", "id": r["sourceId"], "version": 1, "op": "update", "fields": {"work": "けもフレ"}}]}
    )
    again = svc.add([str(f), str(media / ".." / media.name / f.name)])
    assert [x["sourceId"] for x in again] == [r["sourceId"]] * 2
    assert all(x["existing"] for x in again)
    assert svc.get(r["sourceId"])["work"] == "けもフレ"


def test_path_key_normalizes_unicode():
    nfd = unicodedata.normalize("NFD", "/媒体/が.wav")
    assert path_key(nfd) == path_key("/媒体/が.wav")


@needs_ffmpeg
def test_uses_current_infer_rules(svc, db, media):
    db.execute(
        "INSERT INTO setting(key, value, version, updated_at) VALUES ('source.infer_rules', ?, 1, ?)",
        ('["^(?P<work>[a-z]+)_(?P<episode>\\\\d+)$"]', now_iso()),
    )
    [r] = svc.add([str(wav(media / "show_12.wav"))])
    assert (r["work"], r["episode"], r["inferRule"]) == ("show", "12", 0)


# ---------------------------------------------------------------- 快照与重新定位


@needs_ffmpeg
def test_snapshot_detects_change_and_missing(svc, media):
    f = wav(media / "x.wav")
    [r] = svc.add([str(f)])
    svc.check_file(r["sourceId"])
    with open(f, "ab") as fh:
        fh.write(b"\x00")
    with pytest.raises(CoreError) as ei:
        svc.check_file(r["sourceId"])
    assert ei.value.code == "source-changed"
    f.unlink()
    with pytest.raises(CoreError) as ei:
        svc.check_file(r["sourceId"])
    assert ei.value.code == "file-missing"


# R1.3 重新定位到内容不同的文件：只改位置；来回定位身份不变
@needs_ffmpeg
def test_relocate(svc, db, media):
    a = wav(media / "a.wav", seconds=1.0)
    b = wav(media / "b.wav", seconds=2.0, rate=44100)
    [r] = svc.add([str(a)])
    sid = r["sourceId"]
    before = svc.get(sid)
    out = svc.relocate(sid, str(b))
    assert out["streamsChanged"] is True
    after = svc.get(sid)
    assert after["path"] == str(b)
    assert (after["duration"], after["streams"]) == (before["duration"], before["streams"])  # 时间关系不变
    svc.check_file(sid)  # 新快照
    svc.relocate(sid, str(a))
    assert svc.get(sid)["path"] == str(a)
    assert db.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 1
    # 不能定位到另一个原片正在用的文件
    [r2] = svc.add([str(b)])
    with pytest.raises(CoreError) as ei:
        svc.relocate(sid, str(b))
    assert ei.value.code == "source-path-taken"


# ---------------------------------------------------------------- 删除（R1.4）


def _asset(db, source_id, origin="stream", input_asset=None):
    aid = new_id()
    db.execute(
        "INSERT INTO sound_asset(id, source_id, origin, stream_ordinal, duration, mapping, input_asset_id, created_at)"
        " VALUES (?, ?, ?, 0, 1.0, '[[0,0],[1,1]]', ?, ?)",
        (aid, source_id, origin, input_asset, now_iso()),
    )
    return aid


@needs_ffmpeg
def test_delete_cascades_and_keeps_files(svc, db, ws, media):
    f = wav(media / "del.wav")
    [r] = svc.add([str(f)])
    sid = r["sourceId"]
    stream = _asset(db, sid)
    sep = _asset(db, sid, "separation", stream)
    flat = _asset(db, sid, "flatten", sep)  # 生成资产链
    lib = ws.root / "Library" / "Tracks" / "x" / "flat.mp3"
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"mp3")
    mid = new_id()
    db.execute(
        "INSERT INTO media_file(id, path, location, created_at) VALUES (?, ?, 'library', ?)",
        (mid, "Library/Tracks/x/flat.mp3", now_iso()),
    )
    db.execute("UPDATE sound_asset SET media_file_id=? WHERE id=?", (mid, flat))
    s1, s2 = make_sample(db, stream), make_sample(db, flat)
    db.execute(
        "INSERT INTO text_segment(id, source_id, start, \"end\", text, origin, created_at, updated_at) VALUES (?, ?, 0, 1, 'x', 'subtitle', ?, ?)",
        (new_id(), sid, now_iso(), now_iso()),
    )
    db.execute(
        "INSERT INTO range_tag(id, source_id, scope, scope_asset_id, start, \"end\", tags, created_at, updated_at) VALUES (?, ?, 'asset', ?, 0, 1, '[\"x\"]', ?, ?)",
        (new_id(), sid, sep, now_iso(), now_iso()),
    )
    other = svc.add([str(wav(media / "other.wav"))])[0]["sourceId"]
    other_sample = make_sample(db, _asset(db, other))

    pv = svc.delete_preview(sid)
    assert (pv["samples"], pv["generatedAssets"], pv["segments"], pv["rangeTags"], pv["activeJobs"]) == (2, 2, 1, 1, [])

    # 有相关任务时拒绝
    jid = new_id()
    db.execute(
        "INSERT INTO job(id, kind, channel, status, params, device, affects, created_at) VALUES (?, 'x', 'light', 'running', '{}', '{}', ?, ?)",
        (jid, '{"sample": ["%s"]}' % s2, now_iso()),
    )
    with pytest.raises(CoreError) as ei:
        svc.delete(sid)
    assert ei.value.code == "source-has-active-jobs"
    db.execute("UPDATE job SET status='succeeded' WHERE id=?", (jid,))

    svc.delete(sid)
    q = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
    assert q("SELECT COUNT(*) FROM source WHERE id=?", sid) == 0
    assert q("SELECT COUNT(*) FROM sound_asset WHERE source_id=?", sid) == 0
    assert q("SELECT COUNT(*) FROM sample WHERE id IN (?, ?)", s1, s2) == 0
    assert q("SELECT COUNT(*) FROM text_segment WHERE source_id=?", sid) == 0 and q("SELECT COUNT(*) FROM range_tag WHERE source_id=?", sid) == 0
    assert q("SELECT COUNT(*) FROM media_file WHERE id=?", mid) == 0
    assert f.exists()  # 原片文件保留
    assert not lib.exists()  # 为它生成的库内文件删除
    assert q("SELECT COUNT(*) FROM sample WHERE id=?", other_sample) == 1  # 别的原片不受影响


@needs_ffmpeg
def test_delete_refuses_independent_samples_for_now(svc, db, media):
    [r] = svc.add([str(wav(media / "ind.wav"))])
    s = make_sample(db, _asset(db, r["sourceId"]))
    db.execute("UPDATE sample SET independent=1 WHERE id=?", (s,))
    with pytest.raises(CoreError) as ei:
        svc.delete(r["sourceId"])
    assert ei.value.code == "source-has-independent-samples"


def test_batch_relocate_by_relative_path_then_name(db, ws, tmp_path):
    """批量重新定位（ARCHITECTURE §4.10）：先按相对导入根文件夹的路径，再按唯一的文件名；同名多个不猜。"""
    import shutil as _sh
    import subprocess as _sp

    from ottosmasher.core.sources import SourceService

    old = tmp_path / "old"
    (old / "a").mkdir(parents=True)
    for rel in ("a/x.wav", "y.wav", "z.wav"):
        _sp.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=0.5", str(old / rel)], check=True)
    svc = SourceService(db, workspace_root=ws.root)
    added = svc.add([str(old / "a" / "x.wav"), str(old / "y.wav"), str(old / "z.wav")])
    db.execute("UPDATE source SET import_root=?", (str(old),))
    new = tmp_path / "moved"
    _sh.copytree(old, new / "deep")
    (new / "other").mkdir()
    _sh.copy(old / "z.wav", new / "other" / "z.wav")  # z 有两个同名
    _sh.rmtree(old)
    ids = [a["sourceId"] for a in added]
    plan = {p["sourceId"]: p for p in svc.relocate_plan(ids, str(new / "deep"))}
    assert plan[ids[0]]["how"] == "relative" and plan[ids[0]]["path"].replace("\\", "/").endswith("deep/a/x.wav")
    plan2 = {p["sourceId"]: p for p in svc.relocate_plan(ids, str(new))}
    assert plan2[ids[0]]["how"] == "name" and plan2[ids[2]]["how"] == "ambiguous" and plan2[ids[2]]["path"] is None
    done = svc.relocate_many(list(plan.values()))
    assert len(done) == 3
    assert db.execute("SELECT path FROM source WHERE id=?", (ids[1],)).fetchone()[0].replace("\\", "/").endswith("deep/y.wav")
