"""声音资产：登记时的整轨资产、存储、重新定位同步；默认轨资格（规格 16 R2.1–R2.2）。"""

import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.errors import CoreError
from ottosmasher.core.sources import SourceService
from ottosmasher.domain.mapping import Mapping
from test_sources import needs_ffmpeg, two_audio_mkv, wav


@pytest.fixture
def svc(db, ws):
    return SourceService(db, workspace_root=ws.root)


@needs_ffmpeg
def test_each_audio_stream_gets_full_track_asset(svc, db, tmp_path):
    f = two_audio_mkv(tmp_path / "two.mkv", seconds=2.5)
    [r] = svc.add([str(f)])
    sid = r["sourceId"]
    assert [a["ordinal"] for a in r["assets"]] == [0, 1] and all(a["assetId"] for a in r["assets"])
    listed = assets_mod.list_for_source(db, sid)
    assert [(a["origin"], a["stream_ordinal"], a["isFullTrack"], a["roles"]) for a in listed] == [
        ("stream", 0, True, []),  # 原混音默认没有角色
        ("stream", 1, True, []),
    ]
    a = listed[1]
    assert Mapping.of(a["mapping"]) == Mapping.identity(a["duration"])  # 恒等映射
    assert a["language"] == "jpn"
    st = db.execute("SELECT range_start, range_end, kind, media_file_id FROM asset_storage WHERE asset_id=?", (a["id"],)).fetchone()
    assert (st[0], st[1], st[2]) == (0, pytest.approx(2.5), "primary")
    mf = db.execute("SELECT path, location FROM media_file WHERE id=?", (st[3],)).fetchone()
    assert (mf[0], mf[1]) == (str(f), "external")  # 不复制原片


@needs_ffmpeg
def test_relocate_moves_media_file_and_keeps_assets(svc, db, tmp_path):
    a, b = wav(tmp_path / "a.wav"), wav(tmp_path / "b.wav", seconds=1.2)
    [r] = svc.add([str(a)])
    before = assets_mod.list_for_source(db, r["sourceId"])
    svc.relocate(r["sourceId"], str(b))
    after = assets_mod.list_for_source(db, r["sourceId"])
    assert [x["id"] for x in after] == [x["id"] for x in before]
    assert [x["duration"] for x in after] == [x["duration"] for x in before]  # 时间关系不变
    mid = after[0]["media_file_id"]
    assert db.execute("SELECT path FROM media_file WHERE id=?", (mid,)).fetchone()[0] == str(b)


@needs_ffmpeg
def test_delete_removes_media_record_not_file(svc, db, tmp_path):
    f = wav(tmp_path / "d.wav")
    [r] = svc.add([str(f)])
    svc.delete(r["sourceId"])
    assert db.execute("SELECT COUNT(*) FROM media_file").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sound_asset").fetchone()[0] == 0
    assert f.exists()


def _src(db, duration=1.0):
    sid, ts = new_id(), now_iso()
    db.execute("INSERT INTO source(id, path, duration, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (sid, "/x/" + sid, duration, ts, ts))
    return sid


def _asset(db, sid, mapping, roles=("vocal",)):
    aid = new_id()
    m = Mapping.of(mapping)
    db.execute(
        "INSERT INTO sound_asset(id, source_id, origin, duration, mapping, created_at) VALUES (?, ?, 'separation', ?, ?, ?)",
        (aid, sid, m.duration, str(m.to_list()), now_iso()),
    )
    for role in roles:
        db.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, ?, 'on')", (aid, role))
    return aid


# R2.1 默认轨只能选完整覆盖且未变速的资产：逐句资产（0.1–0.4）不行，整轨（0–1）可以
def test_default_track_eligibility(db):
    sid = _src(db, 1.0)
    whole = _asset(db, sid, [[0, 0], [1, 1]])
    clip = _asset(db, sid, [[0, 0.1], [0.3, 0.4]])
    warped = _asset(db, sid, [[0, 0], [0.5, 0.2], [1, 1]])  # R2.2 变速
    nearly = _asset(db, sid, [[0, 0.01], [1.015, 1.015]])  # 20 ms 之内
    no_role = _asset(db, sid, [[0, 0], [1, 1]], roles=())
    assets_mod.check_default_track(db, sid, whole, "vocal")
    assets_mod.check_default_track(db, sid, nearly, "vocal")
    for aid, reason in [(clip, "not-full-track"), (warped, "not-full-track"), (no_role, "missing-role")]:
        with pytest.raises(CoreError) as ei:
            assets_mod.check_default_track(db, sid, aid, "vocal")
        assert ei.value.args_["reason"] == reason
    other = _asset(db, _src(db, 1.0), [[0, 0], [1, 1]])
    with pytest.raises(CoreError) as ei:
        assets_mod.check_default_track(db, sid, other, "vocal")
    assert ei.value.args_["reason"] == "other-source"
    listed = assets_mod.list_for_source(db, sid)
    assert [a["id"] for a in listed if not a["isFullTrack"]] == [clip, warped]
    assert [a["isFullTrack"] for a in listed] == [True, True, True, False, False]  # 整轨在前
