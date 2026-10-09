"""列表行副信息（规格 07 §7.9；UI_PLAN §2.2）：只读已有的测量与索引，缺了不显示（P7）。"""

from __future__ import annotations

import numpy as np

from conftest import make_source
from ottosmasher.core.edits import EditService
from ottosmasher.core.glyphs import Glyphs, _resample
from ottosmasher.core.samples import SampleService
from test_tracks import asset


class NoF0:
    def f0_frames(self, *_a):
        from ottosmasher.core.errors import CoreError

        raise CoreError("f0-missing")


def test_pitch_note_from_tag_and_unknowns(db) -> None:
    src = make_source(db)
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (src,))
    a = asset(db, src, snapshot="a")
    svc = SampleService(db)
    p = svc.create(a, 1, 2, name="p", nature="pitched")["id"]
    u = svc.create(a, 3, 4, name="u", nature="unpitched")["id"]
    sp = svc.create(a, 5, 6, name="s", nature="speech")["id"]
    v = db.execute("SELECT version FROM sample WHERE id=?", (p,)).fetchone()[0]
    EditService(db).apply({"ops": [{"entity": "sample", "id": p, "version": v, "fields": {"local_tags": ["pitch:G♯5"]}}]})
    g = Glyphs(db, NoF0()).get([p, u, sp])
    assert g == {p: {"note": "G♯5"}}  # 没测 F0、没有指标、没有索引：不显示


def test_resample_keeps_unknown_as_none() -> None:
    v = np.array([1.0, 2.0, np.nan, np.nan, 5.0, 6.0])
    r = _resample(v, 3)
    assert r == [1.5, None, 5.5]
