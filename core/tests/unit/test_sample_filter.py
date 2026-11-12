"""采样浏览的条件（规格 07 §7.1–§7.3、16 R8.1–R8.4、R8.6、R8.8；UI_PLAN §2.3）。"""

from __future__ import annotations

import pytest

from conftest import make_source
from ottosmasher.core import sample_filter, text_search
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.samples import SampleService
from test_tracks import asset


@pytest.fixture
def lib(db, ws):
    """两部作品；人物来自段的说话人（人声轨）与本地标签；音高来自本地 pitch: 标签。"""
    edits = EditService(db)
    svc = SampleService(db, reader=text_search.Reader(ws.dictionary))
    yy = make_source(db, work="Yuru Yuri")
    kf = make_source(db, work="Kemono Friends", path="/x/kf.mkv")
    for s in (yy, kf):
        db.execute("UPDATE source SET duration=600.0 WHERE id=?", (s,))
    va = asset(db, yy, origin="separation", stem="vocals", snapshot="v")
    edits.apply({"ops": [{"entity": "asset", "id": va, "version": 1, "fields": {"roles": ["vocal"]}}]})
    vk = asset(db, kf, origin="separation", stem="vocals", snapshot="k")
    edits.apply({"ops": [{"entity": "asset", "id": vk, "version": 1, "fields": {"roles": ["vocal"]}}]})

    def seg(src, a, b, text, speakers):
        edits.apply({"ops": [{"entity": "segment", "op": "create", "fields": {"source_id": src, "start": a, "end": b, "text": text, "speakers": speakers, "origin": "subtitle"}}]})

    seg(yy, 10, 12, "今日はいい天気", ["京子"])
    seg(yy, 20, 22, "やったー！", ["京子", "結衣"])
    seg(yy, 30, 32, "ちょっと待って", ["結衣"])
    seg(kf, 10, 12, "すっごーい！", ["サーバル"])
    ids = {
        "k1": svc.create(va, 10, 12, name="k1")["id"],
        "kmulti": svc.create(va, 20, 22, name="kmulti")["id"],
        "y1": svc.create(va, 30, 32, name="y1")["id"],
        "s1": svc.create(vk, 10, 12, name="s1")["id"],
    }

    def local(key, tags):
        v = db.execute("SELECT version FROM sample WHERE id=?", (ids[key],)).fetchone()[0]
        edits.apply({"ops": [{"entity": "sample", "id": ids[key], "version": v, "fields": {"local_tags": tags}}]})

    local("k1", ["pitch:A4", "好用"])
    local("y1", ["pitch:A4"])
    local("s1", ["pitch:C5"])
    return svc, ids


def names(svc, **f):
    return sorted(r["name"] for r in svc.list(limit=500, **f)["rows"])


def test_sample_search_matches_composed_and_decomposed_names_and_notes(lib, db):
    svc, ids = lib
    db.execute("UPDATE sample SET name=?, note=? WHERE id=?", ("は\u309a%", "が", ids["k1"]))
    assert names(svc, text="ぱ%") == ["は\u309a%"]
    assert names(svc, text="か\u3099") == ["は\u309a%"]


def person(*values, single=False):
    return {"facets": [{"facet": "person", "values": list(values), "single": single}]}


def test_facets_union_within_intersection_across(lib) -> None:
    svc, _ = lib
    # 人物 = 京子 同时匹配 character: 与 participants:；只要单人 → 只匹配 character:
    assert names(svc, tags=person("京子")) == ["k1", "kmulti"]
    assert names(svc, tags=person("京子", single=True)) == ["k1"]
    # 同一分面多个值取并集
    assert names(svc, tags=person("京子", "結衣")) == ["k1", "kmulti", "y1"]
    # 不同分面取交集
    both = {"facets": [{"facet": "work", "values": ["Yuru Yuri"]}, {"facet": "pitch", "values": ["A4"]}]}
    assert names(svc, tags=both) == ["k1", "y1"]
    assert names(svc, tags={"facets": [{"facet": "other", "values": ["好用"]}]}) == ["k1"]


def test_r8_2_scope_main_expression_and_complement(lib) -> None:
    """R8.2：范围（人物 = 京子）∩ 筛选器内容（作品 = Yuru Yuri）∩ 主表达式；NOT 的补集只在范围里取。"""
    svc, _ = lib
    scope = {"facets": [{"facet": "person", "values": ["京子"]}, {"facet": "work", "values": ["Yuru Yuri"]}]}
    assert names(svc, tags=scope, expr='"pitch:A4"') == ["k1"]
    assert names(svc, tags=scope, expr='NOT "pitch:A4"') == ["kmulti"]
    # 前缀通配与范围行的标签表达式
    assert names(svc, tags={"expr": "character:京子 AND NOT participants:*"}) == ["k1"]
    assert names(svc, tags={"expr": "participants:*"}, expr="NOT participants:結衣") == []
    # 性质多选取并集、星标取交集照常（R8.3）
    assert names(svc, natures=["speech", "unclassified"], tags=person("サーバル")) == ["s1"]


def test_expression_errors_name_the_box(lib) -> None:
    svc, _ = lib
    with pytest.raises(CoreError) as ei:
        svc.list(expr="a b")
    assert ei.value.code == "tag-expr-invalid" and ei.value.args_ == {"where": "main", "reason": "expect-operator", "position": 3}
    with pytest.raises(CoreError) as ei:
        svc.list(tags={"expr": "(a"})
    assert ei.value.args_["where"] == "scope"
    with pytest.raises(CoreError):
        svc.list(tags={"facets": [{"facet": "nope", "values": ["x"]}]})


def test_text_matches_name_note_segment_text_and_reading(lib, db) -> None:
    svc, ids = lib
    assert names(svc, text="kmul") == ["kmulti"]  # 名称子串
    assert names(svc, text="天気") == ["k1"]  # 读到的段的原文
    assert names(svc, text="きょう") == ["k1"]  # 读音：今日 → きょー，查询 きょう → きょー
    assert names(svc, text="ヤッター") == ["kmulti"]  # 片假名查询按读音
    assert names(svc, text="すっご〜い") == ["s1"]  # 原文去掉标点后、读音规范化后
    assert names(svc, text="ちょっと、待って") == ["y1"]  # 查询里的标点被去掉
    # 段改了文本 → 搜索跟着变（检索前补齐过期的读音行）
    seg_id = db.execute("SELECT id FROM text_segment WHERE text='ちょっと待って'").fetchone()[0]
    EditService(db).apply({"ops": [{"entity": "segment", "id": seg_id, "version": 1, "fields": {"text": "まだまだ"}}]})
    assert names(svc, text="ちょっと") == []
    assert names(svc, text="まだ") == ["y1"]


def test_ids_equal_list_and_facet_counts(lib) -> None:
    svc, ids = lib
    f = {"tags": person("京子", "サーバル")}
    assert set(svc.ids(**f)) == {r["id"] for r in svc.list(limit=500, **f)["rows"]}
    fv = sample_filter.facet_values(svc.conn)
    people = {x["value"]: (x["count"], x["single"]) for x in fv["person"]}
    assert people["京子"] == (2, 1) and people["結衣"] == (2, 1) and people["サーバル"] == (1, 1)
    assert {x["value"]: x["count"] for x in fv["pitch"]} == {"A4": 2, "C5": 1}
    assert {x["value"]: x["count"] for x in fv["work"]} == {"Kemono Friends": 1, "Yuru Yuri": 3}
    assert any(x["value"] == "speaker-status:多人未分段" for x in fv["other"])


def test_project_filter_matches_exact_local_membership(lib, db) -> None:
    svc, ids = lib
    source = db.execute(
        "SELECT source_id FROM sound_asset JOIN sample ON sample.asset_id=sound_asset.id WHERE sample.id=?",
        (ids["k1"],),
    ).fetchone()[0]
    edits = EditService(db)
    edits.apply({"ops": [{"entity": "range_tag", "op": "create", "fields": {
        "source_id": source, "scope": "source", "start": 10, "end": 22, "tags": ["project:dil"],
    }}]})
    for key, tags in {
        "k1": ["project:dil", "project:other", "好用"], "y1": ["project:dil-remix"], "s1": ["project:dil"],
    }.items():
        v = db.execute("SELECT version FROM sample WHERE id=?", (ids[key],)).fetchone()[0]
        edits.apply({"ops": [{"entity": "sample", "id": ids[key], "version": v, "fields": {"local_tags": tags}}]})
    assert names(svc, expr='"project:dil"') == ["k1", "kmulti", "s1"]  # 普通标签可来自区段
    assert names(svc, projectTag="project:dil") == ["k1", "s1"]
    assert names(svc, projectTag="project:other") == ["k1"]
    assert svc.ids(projectTag="project:dil", tags={"facets": [{"facet": "other", "values": ["好用"]}]}) == [ids["k1"]]


def test_window_predicate_for_source_track_mode(lib, db) -> None:
    """原片音轨模式的音高检索（D1，L28）：范围的标签条件按“查询窗与标注交叠”求值。"""
    from ottosmasher.core import effective_tags

    svc, ids = lib
    va = db.execute("SELECT asset_id FROM sample WHERE id=?", (ids["k1"],)).fetchone()[0]
    pred = sample_filter.tag_predicate({"tags": person("京子", single=True), "expr": "NOT participants:*"})
    win = lambda a, b: {t for t, _p, _r in effective_tags.compute_window(db, va, a, b)}  # noqa: E731
    assert pred(win(10.5, 11.0)) and not pred(win(20.5, 21.0)) and not pred(win(40, 41))
    assert sample_filter.tag_predicate({"text": "x"}) is None
