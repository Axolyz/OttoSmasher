"""采样：截取新建、建议名、性质预填、列表、删除（规格 16 R7.1–R7.5、R2.6、R8.9；04 §4.5）。"""

import time

import pytest

from conftest import make_source
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.errors import CoreError
from ottosmasher.core.samples import SampleService


def asset(db, sid, *, roles=(), duration=100.0, mapping=None, language="ja"):
    aid = new_id()
    m = mapping or f"[[0,0],[{duration},{duration}]]"
    db.execute(
        "INSERT INTO sound_asset(id, source_id, origin, stream_ordinal, duration, mapping, language, created_at)"
        " VALUES (?, ?, 'stream', 0, ?, ?, ?, ?)",
        (aid, sid, duration, m, language, now_iso()),
    )
    db.execute("INSERT INTO source_stream(source_id, kind, ordinal, container_index, sample_rate) VALUES (?, 'audio', 0, 0, 48000)", (sid,))
    for r in roles:
        db.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, ?, 'on')", (aid, r))
    return aid


@pytest.fixture
def svc(db):
    return SampleService(db)


@pytest.fixture
def src(db):
    return make_source(db, work="Yuru Yuri", episode="01", path="/m/[x] Yuru Yuri [01].mkv")


def annotate(db, sid, kind, start, end, text, deleted=0):
    """文本层的段（kind=line）或音效提示（kind=sfx）。"""
    if kind == "line":
        db.execute(
            'INSERT INTO text_segment(id, source_id, start, "end", text, origin, deleted, created_at, updated_at) VALUES (?, ?, ?, ?, ?, \'subtitle\', ?, ?, ?)',
            (new_id(), sid, start, end, text, deleted, now_iso(), now_iso()),
        )
    else:
        db.execute(
            'INSERT INTO sfx_hint(id, source_id, start, "end", text, origin, deleted, created_at, updated_at) VALUES (?, ?, ?, ?, ?, \'subtitle\', ?, ?, ?)',
            (new_id(), sid, start, end, text, deleted, now_iso(), now_iso()),
        )


def test_suggest_name_rules(db, svc, src):
    aid = asset(db, src)
    assert svc.suggest(aid, 80.2, 82.0)["name"] == "Yuru Yuri 01 1:20.200–1:22.000"
    # R7.5 与段 / 音效提示交叠 → 用它们的文字；端点相接不算交叠；已删除的不算
    annotate(db, src, "sfx", 82.0, 83.0, "足音")
    annotate(db, src, "line", 79.0, 80.5, "ちょっと待って")
    annotate(db, src, "line", 81.0, 81.5, "消した", deleted=1)
    assert svc.suggest(aid, 80.2, 82.0)["name"] == "ちょっと待って"
    assert svc.suggest(aid, 81.9, 82.5)["name"] == "足音"


def test_suggest_uses_source_time_through_mapping(db, svc, src):
    aid = asset(db, src, duration=2.0, mapping="[[0,100],[2,102]]")  # 原片 100–102 秒的一段
    annotate(db, src, "line", 100.5, 101.0, "やったー")
    assert svc.suggest(aid, 0.4, 0.6)["name"] == "やったー"
    assert svc.suggest(aid, 1.2, 1.4)["name"] == "Yuru Yuri 01 1:41.200–1:41.400"


@pytest.mark.parametrize("roles,nature", [(("vocal",), "speech"), (("sfx",), "unpitched"), (("vocal", "sfx"), "unclassified"), ((), "unclassified")])
def test_nature_prefill_by_role(db, svc, src, roles, nature):
    aid = asset(db, src, roles=roles)
    assert svc.suggest(aid, 1, 2)["nature"] == nature
    assert svc.create(aid, 1, 2, name="x")["nature"] == nature
    assert svc.create(aid, 1, 2, name="x", nature="pitched")["nature"] == "pitched"  # 显式给的生效


# R7.1 显式保存一律新建；R7.2 直接绑定资产选区
def test_save_twice_makes_two(db, svc, src):
    aid = asset(db, src)
    a = svc.create(aid, 1.0, 2.0, name="やったー")
    b = svc.create(aid, 1.0, 2.0, name="やったー")
    assert a["id"] != b["id"]
    assert (b["asset_id"], b["start"], b["end"], b["created_via"]) == (aid, 1.0, 2.0, "manual")
    assert b["source_start"] == 1.0 and b["duration"] == 1.0 and b["source_name"] == "Yuru Yuri 01"
    assert db.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0


def test_create_validation(db, svc, src):
    aid = asset(db, src, duration=10.0)
    assert svc.create(aid, 9.5, 10 + 1 / 48000, name="end")["end"] == 10.0  # 一帧舍入
    for kw, code in [
        (dict(start=9.5, end=10.1, name="x"), "range-invalid"),
        (dict(start=2, end=2, name="x"), "range-invalid"),
        (dict(start=1, end=2, name="  "), "sample-invalid"),
        (dict(start=1, end=2, name="x", nature="loud"), "sample-invalid"),
    ]:
        with pytest.raises(CoreError) as ei:
            svc.create(aid, kw.pop("start"), kw.pop("end"), **kw)
        assert ei.value.code == code


# R7.4 删除父采样后子采样保留“已删除的父采样”来源记录
def test_delete_parent_keeps_child_label(db, svc, src):
    aid = asset(db, src)
    parent = svc.create(aid, 1, 3, name="親")
    child = svc.create(aid, 1.5, 2, name="子", parent_sample_id=parent["id"])
    svc.delete([parent["id"]])
    c = svc.get(child["id"])
    assert c["parent_sample_id"] is None and c["parent_label"] == "親"
    with pytest.raises(CoreError):
        svc.get(parent["id"])


def test_delete_refuses_active_jobs(db, svc, src):
    s = svc.create(asset(db, src), 1, 2, name="x")
    db.execute(
        "INSERT INTO job(id, kind, channel, status, params, device, affects, created_at) VALUES (?, 'x', 'light', 'queued', '{}', '{}', ?, ?)",
        (new_id(), '{"sample": ["%s"]}' % s["id"], now_iso()),
    )
    with pytest.raises(CoreError) as ei:
        svc.delete([s["id"]])
    assert ei.value.code == "sample-has-active-jobs"


def test_list_filters_and_paging(db, svc, src):
    aid = asset(db, src)
    for i in range(5):
        svc.create(aid, i, i + 0.5, name=f"台詞{i}", nature="speech" if i % 2 else "unpitched")
    db.execute("UPDATE sample SET starred=1 WHERE name='台詞3'")
    page = svc.list(limit=2)
    assert page["total"] == 5 and [r["name"] for r in page["rows"]] == ["台詞4", "台詞3"]  # 新的在前
    assert svc.list(natures=["speech"])["total"] == 2
    assert svc.list(natures=["speech", "unpitched"])["total"] == 5  # 性质取并集
    assert [r["name"] for r in svc.list(natures=["speech"], starred=True)["rows"]] == ["台詞3"]  # 星标取交集
    assert svc.list(text="詞2")["total"] == 1
    assert svc.list(text="%")["total"] == 0  # 通配符按字面
    assert [r["name"] for r in svc.list(sort="name", limit=2)["rows"]] == ["台詞0", "台詞1"]
    assert len(svc.ids(natures=["unpitched"])) == 3
    with pytest.raises(CoreError):
        svc.list(sort="nope")


# R8.9 10,001 条按标题排序取第 101–200 条 < 3 秒；“选全部匹配”返回全部 ID
def test_paging_10k(db, svc, src):
    aid = asset(db, src, duration=20000.0)
    ts = now_iso()
    db.executemany(
        'INSERT INTO sample(id, asset_id, start, "end", name, nature, created_via, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
        [(new_id(), aid, i, i + 0.5, f"s{i:05d}", "speech", "manual", ts, ts) for i in range(10001)],
    )
    t = time.perf_counter()
    page = svc.list(offset=100, limit=100, sort="name")
    assert time.perf_counter() - t < 3
    assert page["total"] == 10001 and page["rows"][0]["name"] == "s00100" and len(page["rows"]) == 100
    assert len(svc.ids()) == 10001
