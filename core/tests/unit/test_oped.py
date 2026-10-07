"""OP/ED：规格 05 §5.6、16 R6.1–R6.4（合成字幕）。"""

import pytest

from conftest import make_source
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.oped import OpedService
from ottosmasher.domain import oped_rule
from ottosmasher.domain.subtitles import Cue

S, E = "♪～", "～♪"


def cues(*items):
    return [Cue(order=i + 1, ref=str(i + 1), start=a, end=b, text=t, line=i + 1) for i, (a, b, t) in enumerate(items)]


def ident(items, duration=200.0, starts=(S,), ends=(E,)):
    return oped_rule.identify(cues(*items), duration, starts, ends)


def test_markers_exact_after_whitespace_and_wave_dash():
    r = ident([(10, 12, " ♪〜 "), (40, 41, "♪ 歌詞"), (60, 61, "♪～ あ"), (88, 90, "〜　♪")])
    assert [(p.start, p.end, p.suggest) for p in r.pairs] == [(10, 90, "OP")]
    assert r.errors == []


def test_single_interval_by_midpoint_and_two_in_order():
    assert [p.suggest for p in ident([(10, 11, S), (89, 90, E)]).pairs] == ["OP"]
    assert [p.suggest for p in ident([(150, 151, S), (198, 199, E)]).pairs] == ["ED"]
    # 两对：依次 OP、ED（即使都在前半片）
    r = ident([(10, 11, S), (20, 21, E), (30, 31, S), (40, 41, E)])
    assert [(p.start, p.end, p.suggest) for p in r.pairs] == [(10, 21, "OP"), (30, 41, "ED")]


@pytest.mark.parametrize(
    "items,code",
    [
        ([(10, 11, S), (20, 21, S), (30, 31, E)], "duplicate-start"),
        ([(10, 11, E)], "end-without-start"),
        ([(10, 11, S)], "start-without-end"),
        ([(150, 151, S), (205, 206, E)], "out-of-range"),
        ([(1, 2, S), (3, 4, E), (5, 6, S), (7, 8, E), (9, 10, S), (11, 12, E)], "too-many"),
    ],
)
def test_errors_are_reported(items, code):
    r = ident(items)
    assert code in [e["code"] for e in r.errors]


def test_too_many_still_lists_pairs_for_confirmation():
    r = ident([(1, 2, S), (3, 4, E), (5, 6, S), (7, 8, E), (150, 160, S), (170, 180, E)])
    assert [(p.start, p.end, p.suggest) for p in r.pairs] == [(1, 4, "OP"), (5, 8, "OP"), (150, 180, "ED")]


def test_custom_markers():
    r = ident([(10, 11, "【OP】"), (80, 81, "【/OP】")], starts=["【OP】"], ends=["【/OP】"])
    assert len(r.pairs) == 1


# ---------- 服务


def srt(*items):
    def ts(x):
        return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{round(x % 1 * 1000):03d}"

    return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(items, start=1))


@pytest.fixture
def env(db, tmp_path):
    sid = make_source(db)
    p = tmp_path / "a.srt"
    p.write_text(srt((10, 11, S), (12, 13, "（京子）台詞"), (88, 90, E), (150, 151, S), (198, 199, E)), encoding="utf-8")
    db.execute("UPDATE source SET duration=200.0, subtitle_path=? WHERE id=?", (str(p), sid))
    edits = EditService(db)
    return sid, p, OpedService(db, edits), edits


def test_identify_registers_and_is_idempotent(db, env):
    sid, _, svc, _ = env
    r = svc.identify(sid)
    assert (r["applied"], r["errors"]) == (2, [])
    assert [(o["kind"], o["start"], o["end"], o["via"]) for o in svc.list(sid)] == [("OP", 10, 90, "rule"), ("ED", 150, 199, "rule")]
    # 幂等：再识别一次不重复登记
    r2 = svc.identify(sid)
    assert (r2["applied"], r2["skippedOverlap"]) == (0, 2)
    assert len(svc.list(sid)) == 2


def test_rule_does_not_overwrite_manual(db, env):
    sid, _, svc, _ = env
    svc.add(sid, "OP", 5.0, 50.0, "mark")
    r = svc.identify(sid)
    assert r["applied"] == 1  # 只登记 ED
    assert [(o["kind"], o["start"], o["via"]) for o in svc.list(sid)] == [("OP", 5.0, "mark"), ("ED", 150, "rule")]


def test_errors_register_nothing_but_pairs_can_be_confirmed(db, env):
    sid, p, svc, _ = env
    p.write_text(srt((10, 11, S), (20, 21, S), (88, 90, E)), encoding="utf-8")
    r = svc.identify(sid)
    assert [e["code"] for e in r["errors"]] == ["duplicate-start"]
    assert r["applied"] == 0 and svc.list(sid) == []
    pair = r["pairs"][0]
    svc.add(sid, "OP", pair["start"], pair["end"], "confirm", pair["refs"])
    assert [(o["kind"], o["via"]) for o in svc.list(sid)] == [("OP", "confirm")]


def test_manual_mark_validation_and_undoable_delete(db, env):
    sid, _, svc, edits = env
    with pytest.raises(CoreError) as e:
        svc.add(sid, "OP", 190.0, 210.0, "mark")
    assert e.value.args_["reason"] == "out-of-source"
    with pytest.raises(CoreError):
        svc.add(sid, "XX", 1.0, 2.0, "mark")
    oid = svc.add(sid, "ED", 150.0, 190.0, "mark")["id"]
    with pytest.raises(CoreError) as e:
        svc.add(sid, "OP", 189.0, 195.0, "mark")  # 交叠
    assert e.value.code == "oped-overlap"
    svc.add(sid, "OP", 190.0, 195.0, "mark")  # 端点相接不算交叠
    svc.delete(oid)
    assert [o["start"] for o in svc.list(sid)] == [190.0]
    edits.undo()  # 撤销删除
    assert sorted(o["start"] for o in svc.list(sid)) == [150.0, 190.0]


def test_identify_needs_subtitle(db, env):
    _, _, svc, _ = env
    other = make_source(db, path="/m/other.mkv")
    with pytest.raises(CoreError) as e:
        svc.identify(other)
    assert e.value.code == "subtitle-not-associated"
    rows = svc.identify_many([other])
    assert rows[0]["error"]["code"] == "subtitle-not-associated"


def test_marker_settings_validation(db):
    edits = EditService(db)
    edits.apply({"ops": [{"entity": "setting", "id": "subtitle.oped_start", "version": 0, "fields": {"value": ["♪～", "♪〜♪"]}}]})
    with pytest.raises(CoreError):
        edits.apply({"ops": [{"entity": "setting", "id": "subtitle.oped_end", "version": 0, "fields": {"value": ["  "]}}]})
