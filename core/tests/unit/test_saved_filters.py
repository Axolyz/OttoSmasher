"""保存筛选器（规格 07 §7.3、16 R8.5；Q16：只存标签条件）：新建 / 改名 / 更新 / 删除 / 排序都走编辑通道、可撤销。"""

from __future__ import annotations

import pytest

from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.saved_filters import list_filters

YY = {"facets": [{"facet": "work", "values": ["Yuru Yuri"]}]}


def create(edits, name, cond, order):
    return edits.apply({"label": {"code": "filter-save", "args": {"name": name}},
                        "ops": [{"entity": "saved_filter", "op": "create", "fields": {"name": name, "conditions": cond, "sort_order": order}}]})["changes"][0]["id"]


def test_crud_reorder_and_undo(db) -> None:
    edits = EditService(db)
    a = create(edits, "Yuru Yuri", YY, 0)
    b = create(edits, "京子单人", {"facets": [{"facet": "person", "values": ["京子"], "single": True}], "expr": "NOT participants:*"}, 1)
    assert [f["name"] for f in list_filters(db)] == ["Yuru Yuri", "京子单人"]
    assert list_filters(db)[0]["conditions"] == {"facets": [{"facet": "work", "values": ["Yuru Yuri"], "single": False}], "expr": ""}
    # 原子排序：一次编辑改两个
    fa, fb = list_filters(db)
    edits.apply({"label": {"code": "filter-reorder"}, "ops": [
        {"entity": "saved_filter", "id": a, "version": fa["version"], "fields": {"sort_order": 1}},
        {"entity": "saved_filter", "id": b, "version": fb["version"], "fields": {"sort_order": 0}},
    ]})
    assert [f["name"] for f in list_filters(db)] == ["京子单人", "Yuru Yuri"]
    edits.undo()
    assert [f["name"] for f in list_filters(db)] == ["Yuru Yuri", "京子单人"]
    # 删除 = 软删除，可撤销
    v = next(f for f in list_filters(db) if f["id"] == b)["version"]
    edits.apply({"ops": [{"entity": "saved_filter", "id": b, "version": v, "fields": {"deleted": True}}]})
    assert [f["name"] for f in list_filters(db)] == ["Yuru Yuri"]
    edits.undo()
    assert len(list_filters(db)) == 2
    # 撤销新建 = 软删除
    create(edits, "临时", YY, 2)
    edits.undo()
    assert [f["name"] for f in list_filters(db)] == ["Yuru Yuri", "京子单人"]


@pytest.mark.parametrize("cond", [
    {"facets": [], "expr": "a b"},  # 表达式不能解析
    {"text": "天気"},  # 文字不能进筛选器（Q16）
    {"facets": [{"facet": "nature", "values": ["speech"]}]},  # 性质不是分面
    "work:x",
])
def test_rejects_non_tag_conditions(db, cond) -> None:
    with pytest.raises(CoreError) as ei:
        create(EditService(db), "x", cond, 0)
    assert ei.value.code == "edit-invalid" and ei.value.args_["field"] == "conditions"
