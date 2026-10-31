"""文本层搜索（所有者 2026-10-31）：搜原料（段与音效提示），结果是原片上的位置；规则同采样的“原句”筛选（规范化原文 / 读音子串）。"""

import pytest

from conftest import make_source
from ottosmasher.core import text_search as ts
from ottosmasher.core.errors import CoreError
from test_text_layer import setup


def test_text_hits_spans_hints_and_scope(db, tmp_path):
    a, _, _ = setup(db, tmp_path, [(1, 2, "（京子）今日はいい天気！"), (3, 4, "（足音）"), (5, 6, "（結衣）ＴＥＮＫＩ予報"), (7, 8, "明日は雨")])
    r = ts.search_layer(db, None, "いい 天気")  # 空白、标点不算
    assert r["total"] == 1 and r["notImported"] == [] and r["bySource"] == [{"sourceId": a, "count": 1}]
    h = r["hits"][0]
    assert (h["kind"], h["text"], h["speakers"], h["match"], h["start"]) == ("segment", "今日はいい天気！", ["京子"], "text", 1.0)
    assert h["spans"] == [[3, 7]]  # 原文里的「いい天気」
    assert [x["text"] for x in ts.search_layer(db, None, "tenki")["hits"]] == ["ＴＥＮＫＩ予報"]  # 全角 / 大小写统一
    assert [(x["kind"], x["text"]) for x in ts.search_layer(db, None, "足音")["hits"]] == [("hint", "足音")]
    assert ts.search_layer(db, None, "足音", hints=False)["total"] == 0
    assert [x["text"] for x in ts.search_layer(db, None, "は", speakers=["結衣", "京子"])["hits"]] == ["今日はいい天気！"]
    # 只搜某几个原素材；另一个原素材关联了字幕但还没导入 → 报出来
    b = make_source(db, path="/other.mkv")
    db.execute("UPDATE source SET subtitle_path='/other.srt' WHERE id=?", (b,))
    assert ts.search_layer(db, None, "雨")["notImported"] == [b]
    assert ts.search_layer(db, None, "雨", source_ids=[b]) == {"query": "雨", "total": 0, "hits": [], "bySource": [], "notImported": [b], "readingPending": 0}
    assert ts.search_layer(db, None, "！？")["total"] == 0  # 只有标点 = 没有可搜的
    with pytest.raises(CoreError):
        ts.search_layer(db, None, "x", limit=0)


def test_reading_hits_use_the_index_and_paging(db, tmp_path):
    setup(db, tmp_path, [(1, 2, "今日は"), (3, 4, "きょうも"), (5, 6, "京")])
    # 读音来自 segment_search（Core 里由 pyopenjtalk 算；这里直接写进去）
    for sid, text, reading in db.execute("SELECT id, text, ? FROM text_segment", ("",)).fetchall():
        rd = {"今日は": "きょうは", "きょうも": "きょうも", "京": "きょう"}[text]
        db.execute("INSERT INTO segment_search(segment_id, text, dict_version, norm, reading) VALUES (?, ?, 'v', ?, ?)", (sid, text, ts.norm(text), rd))
    r = ts.search_layer(db, None, "きょう")
    assert [(h["text"], h["match"], h["spans"]) for h in r["hits"]] == [("今日は", "reading", []), ("きょうも", "text", [[0, 3]]), ("京", "reading", [])]
    page = ts.search_layer(db, None, "きょう", limit=1, offset=1)
    assert page["total"] == 3 and [h["text"] for h in page["hits"]] == ["きょうも"]
    # 段文字改过、读音还没重算：只按原文匹配（不拿旧读音冒充）
    db.execute("UPDATE text_segment SET text='みやこ' WHERE text='京'")
    assert [h["text"] for h in ts.search_layer(db, None, "きょう")["hits"]] == ["今日は", "きょうも"]


def test_norm_spans_maps_back_to_the_original():
    assert ts.norm_spans("Ａ、Ｂ　ｃ", "abc") == [[0, 5]]
    assert ts.norm_spans("はい、はい", "はい") == [[0, 2], [3, 5]]
    assert ts.norm_spans("x", "") == []


def test_real_reader_finds_kanji_by_reading(db, ws, tmp_path):
    """真实读音（pyopenjtalk-plus + 用户辞典）：搜「きょう」找到「今日」；检索前顺手补齐索引。"""
    setup(db, tmp_path, [(1, 2, "今日はいい天気"), (3, 4, "明日")])
    r = ts.search_layer(db, ts.Reader(ws.dictionary), "きょう")
    assert [(h["text"], h["match"]) for h in r["hits"]] == [("今日はいい天気", "reading")] and r["readingPending"] == 0
