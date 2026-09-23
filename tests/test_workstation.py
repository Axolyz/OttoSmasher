import json
import time
from pathlib import Path

import numpy as np
import pysubs2
import pytest
from test_samples import library as library  # noqa: PLC0414

from ottosmasher import materials
from ottosmasher import opening_subtitles as sub
from ottosmasher import sample_catalog as samples
from ottosmasher import ui_catalog as ui


def event(text, start, end):
    return pysubs2.SSAEvent(text=text, start=int(start * 1000), end=int(end * 1000))


def test_music_markers_single_half_and_exact_tokens():
    assert sub.detect([event("{\\i1} ♪〜 ", 10, 11), event("〜♪", 80, 90)], 200)["pairs"] == [
        {"start": 10, "end": 90, "kind": "op"}
    ]
    assert sub.detect([event("♪～", 150, 151), event("～♪", 190, 199)], 200)["pairs"][0]["kind"] == "ed"
    assert not sub.detect([event("♪ 歌詞", 10, 90)], 200)["automatic"]
    assert not sub.detect([event("♪～", 10, 11), event("♪～", 20, 21), event("～♪", 80, 90)], 200)[
        "automatic"
    ]
    assert not sub.detect([event("～♪", 80, 90)], 200)["automatic"]


def test_music_pairs_and_ambiguity():
    events = [event("♪～", 10, 11), event("～♪", 90, 100), event("♪～", 170, 171), event("～♪", 190, 195)]
    r = sub.detect(events, 200)
    assert r["automatic"] and [p["kind"] for p in r["pairs"]] == ["op", "ed"]
    assert not sub.detect(events + [event("♪～", 196, 197), event("～♪", 198, 199)], 200)["automatic"]


def test_live_tags_range_overrides_and_custom_defaults(library):
    db, root, _ = library
    ui.label_source(db, root["source_id"], work="作品一", media_type="动画")
    materials.edit(db, root["id"], tags=["私有备注", "可继承"])
    ui.ensure(db)
    db.execute("INSERT INTO tag_rules VALUES('可继承',1)")
    child = samples.derive(db, root["id"], start=0.1, end=0.3)

    def labels(mid):
        return {t["tag"] for t in materials.get(db, mid)["tags"]}

    assert {"work:作品一", "type:动画", "可继承"} <= labels(child["id"])
    assert "私有备注" not in labels(child["id"])
    ui.label_source(db, root["source_id"], work="作品二")
    assert "work:作品二" in labels(child["id"]) and "work:作品一" not in labels(child["id"])
    db.execute("INSERT INTO tag_overrides VALUES(?,?,?)", (child["id"], "work", "本地名称"))
    ui.label_source(db, root["source_id"], work="作品三")
    assert "work:本地名称" in labels(child["id"]) and "work:作品三" not in labels(child["id"])
    db.execute(
        "INSERT INTO speaker_annotations VALUES(?,?,?,?,?,?,?)",
        ("a", root["source_id"], 0, 0.5, "角色甲", "action", 1),
    )
    db.execute(
        "INSERT INTO speaker_annotations VALUES(?,?,?,?,?,?,?)",
        ("b", root["source_id"], 0.5, 1, "角色乙", "action", 2),
    )
    assert "character:角色甲" in labels(child["id"]) and "character:角色乙" not in labels(child["id"])
    assert child["id"] in materials.query_ids(db, tags=["character:角色甲"])


def test_summary_ten_thousand_no_analysis_payload(library):
    db, root, _ = library
    ui.ensure(db)
    db.executemany(
        "INSERT INTO materials(id,source_id,start,end,audio_stream,title,created) VALUES(?,?,?,?,?,?,?)",
        [
            (f"fixture-{i}", root["source_id"], 0, 0.9, root["audio_stream"], f"样本{i:05}", i)
            for i in range(10000)
        ],
    )
    began = time.perf_counter()
    r = ui.listing(db, {"offset": 100, "limit": 100, "sort": "title", "order": "asc"})
    assert r["total"] == 10001 and len(r["results"]) == 100
    assert all("source_metadata" not in x and "analysis_status" not in x for x in r["results"])
    assert time.perf_counter() - began < 3


def test_visual_vector_scores_and_pts_cache(tmp_path, monkeypatch):
    from ottosmasher import visual_index as vi

    monkeypatch.setattr(vi, "DATA", tmp_path)
    path = tmp_path / "video"
    path.write_bytes(b"video")
    frames = np.random.default_rng(0).integers(0, 255, (4, 14, 24, 3), dtype=np.uint8)
    calls = []

    def decode(*args, **kwargs):
        calls.append(kwargs)
        yield from zip([0, 0.041, 0.109, 0.151], frames)

    monkeypatch.setattr(vi, "decoded", decode)
    t, f, s = vi.index(path, 0, 1)
    assert not s["cached"]
    t2, f2, s2 = vi.index(path, 0, 1)
    assert s2["cached"] and len(calls) == 1
    np.testing.assert_array_equal(t, t2)
    np.testing.assert_array_equal(f, f2)
    assert list(t) == [0, 0.041, 0.109, 0.151]
    assert vi.scores(f, f[2].astype(np.float32) / 255).argmax() == 2
    path.write_bytes(b"different")
    assert not vi.index(path, 0, 1)[2]["cached"]


def test_visual_failed_cache_not_published(tmp_path, monkeypatch):
    from ottosmasher import visual_index as vi

    monkeypatch.setattr(vi, "DATA", tmp_path)
    p = tmp_path / "v"
    p.write_bytes(b"video")

    def broken(*a, **k):
        yield 0, np.zeros((14, 24, 3), dtype=np.uint8)
        raise ValueError("decoder failed")

    monkeypatch.setattr(vi, "decoded", broken)
    with pytest.raises(ValueError):
        vi.index(p, 0, 1)
    assert not list((tmp_path / "cache/visual-index").glob("*.npz"))


def test_source_names_do_not_treat_episode_or_release_as_work():
    assert ui.infer_name("[VCB-Studio] Yuru Yuri [01][1080p].mkv") == ("Yuru Yuri", "01")
    assert ui.infer_name("[DBD-Raws][Kemono Friends][02][1080P].mkv") == ("Kemono Friends", "02")
    assert ui.infer_name("[Kemono Friends][01].mkv") == ("Kemono Friends", "01")


def test_music_apply_is_provenanced_idempotent_and_respects_manual(library, tmp_path):
    from ottosmasher import source_preparation as prep
    from ottosmasher import source_regions

    db, root, _ = library
    p = tmp_path / "markers.srt"
    p.write_text("1\n00:00:00,010 --> 00:00:00,020\n♪～\n\n2\n00:00:00,250 --> 00:00:00,300\n～♪\n")
    prep.configure(db, root["source_id"], subtitle_path=str(p))
    first = sub.run(db, [root["source_id"]])["sources"][0]
    assert len(first["applied"]) == 1
    saved = source_regions.listing(db, root["source_id"])[0]
    assert saved["origin"] == "subtitle-rule" and not json.loads(saved["payload"])["verified"]
    assert not sub.run(db, [root["source_id"]])["sources"][0]["applied"]
    source_regions.remove(db, saved["id"])
    manual = source_regions.confirm(db, root["source_id"], 0, 0.4, kind="ed")
    assert not sub.run(db, [root["source_id"]])["sources"][0]["applied"]
    assert source_regions.listing(db, root["source_id"])[0]["id"] == manual["id"]


def test_direct_import_keeps_review_status_and_rejects_bad_timestamps(library, tmp_path, monkeypatch):
    from contextlib import contextmanager

    from ottosmasher import preparation_api
    from ottosmasher import source_preparation as prep

    db, root, _ = library

    @contextmanager
    def database():
        yield db

    monkeypatch.setattr(preparation_api, "database", database)
    p = tmp_path / "dialogue.srt"
    p.write_text("1\n00:00:00,000 --> 00:00:00,300\nねえ\n")
    prep.configure(db, root["source_id"], subtitle_path=str(p), op_review="reviewed")
    preparation_api.direct_import({"source_id": root["source_id"]})
    assert prep.preview(db, root["source_id"])["op_review"] == "reviewed"
    before = db.execute("SELECT count(*) FROM materials").fetchone()[0]
    preparation_api.direct_import({"source_id": root["source_id"]})
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == before
    p.write_text("1\n00:00:00,500 --> 00:00:00,100\nbad\n")
    with pytest.raises(ValueError, match="无效"):
        preparation_api.direct_import({"source_id": root["source_id"]})


def test_export_directory_preserves_asset_and_avoids_overwrite(library, tmp_path):
    db, root, _ = library
    destination = tmp_path / "持久导出"
    destination.mkdir()
    ui.settings(db, {"export_directory": str(destination)})
    source = Path(root["path"])
    (destination / source.name).write_bytes(b"existing")
    output = ui.place_export(db, {"path": str(source), "material_id": root["id"]})
    assert Path(output["path"]).read_bytes() == source.read_bytes()
    assert Path(output["path"]).parent == destination
    assert (destination / source.name).read_bytes() == b"existing"
    assert source.exists()
