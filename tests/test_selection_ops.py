import json
import numpy as np
import pytest
import soundfile as sf
from test_samples import library
from ottosmasher import asset_migration, asset_timeline as t, selection_ops as ops


def test_save_reimport_and_parent_deletion(library, tmp_path):
    from ottosmasher.sample_deletion import remove
    from ottosmasher.sample_audio import resolve

    db, root, _ = library
    asset_migration.activate(db)
    selection = ops.from_sample(db, root["id"], 0.2, 0.7)
    cut = ops.save(db, selection, title="选区")
    assert t.sample_selection(db, cut["id"]).asset_id == selection.asset_id
    output = tmp_path / "processed.wav"
    sf.write(output, np.zeros(24000), 48000)
    child = ops.external_import(db, selection, output, title="成品")
    bound = resolve(db, child["id"])
    assert bound["speech_analysis_eligible"] is False
    assert bound["root_knots"] == [[0, 0.2], [0.5, 0.7]]
    assert any(r["id"] == child["id"] for r in ops.descendants(db, ops.from_sample(db, root["id"])))
    remove(db, [root["id"]])
    db.commit()
    assert resolve(db, child["id"]) == bound
    sf.write(output, np.zeros(24002), 48000)
    longer = ops.external_import(db, selection, output, title="更长成品")
    assert resolve(db, longer['id'])['end'] == pytest.approx(24002 / 48000)
    sf.write(output, np.zeros(48000), 48000)
    before = db.execute('SELECT count(*) FROM materials').fetchone()[0]
    with pytest.raises(ValueError, match="超出当前资产边界"):
        ops.external_import(db, selection, output)
    assert db.execute('SELECT count(*) FROM materials').fetchone()[0] == before


def test_scoped_labels_do_not_leak_to_music(library):
    from ottosmasher.ui_catalog import effective_all

    db, root, _ = library
    asset_migration.activate(db)
    original = ops.from_sample(db, root["id"])
    descriptor = t.selection_asset(db, original)
    vocals = t.register_asset(db, root["source_id"], {**descriptor, "role": "vocals"})
    music = t.register_asset(db, root["source_id"], {**descriptor, "role": "music"})
    first = ops.save(db, vocals, title="对白")
    second = ops.save(db, music, title="音乐")
    db.execute(
        "INSERT INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
        (
            "speaker",
            root["source_id"],
            0.1,
            0.5,
            "tag",
            "",
            json.dumps(["character:京子"]),
            json.dumps({"type": "group", "ids": ["dialogue"]}),
        ),
    )
    rows = effective_all(db, [first["id"], second["id"]])
    assert "character:京子" in {r["tag"] for r in rows[first["id"]]}
    assert "character:京子" not in {r["tag"] for r in rows[second["id"]]}
    endpoint = ops.save(db, t.AssetSelection(vocals.asset_id, 0.5, 0.8), title="端点")
    assert "character:京子" not in {r["tag"] for r in effective_all(db, [endpoint["id"]])[endpoint["id"]]}


def test_pitch_source_tags_use_overlap_without_sample_dependency(library):
    from ottosmasher.pitch_scope import tag_ranges

    db, root, _ = library
    asset_migration.activate(db)
    sel = ops.from_sample(db, root["id"])
    row = db.execute("SELECT * FROM sound_assets WHERE id=?", (sel.asset_id,)).fetchone()
    db.execute(
        "INSERT INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
        ("span", root["source_id"], 0.4, 0.6, "tag", "", '["wanted"]', '{"type":"source","ids":[]}'),
    )
    ranges = tag_ranges(db, row, 0.2, {"tag_expression": "wanted"})
    # A query ending exactly at .4 or beginning exactly at .6 does not overlap.
    assert ranges[0][0] == pytest.approx(0.21)
    assert ranges[-1][1] - 0.2 == pytest.approx(0.59)
    complement = tag_ranges(db, row, 0.2, {"tag_expression": "NOT wanted"})
    assert complement == pytest.approx([(0, 0.4), (0.6, 1)])


def test_source_index_preparation_respects_track_and_source_filters(library):
    from ottosmasher.pitch_indexing import selection_scope

    db, root, _ = library
    asset_migration.activate(db)
    original = ops.from_sample(db, root["id"])
    descriptor = t.selection_asset(db, original)
    music = t.register_asset(db, root["source_id"], {**descriptor, "role": "music"})
    assert selection_scope(db, {"mode": "sources", "roles": ["music"]}) == {"asset_ids": [music.asset_id]}
    assert selection_scope(db, {"mode": "sources", "scope": {"text": "nonexistent source name"}}) == {
        "asset_ids": []
    }
    assert selection_scope(db, {"mode": "sources", "scope": {"tag_expression": "absent"}}) == {
        "asset_ids": []
    }
    with pytest.raises(ValueError, match="采样"):
        selection_scope(db, {"mode": "sources", "scope": {"material_ids": ["x"]}})


def test_legacy_partial_mapping_displays_only_recorded_coverage(library):
    from ottosmasher.selection_names import suggest

    db, root, _ = library
    asset_migration.activate(db)
    base = ops.from_sample(db, root["id"])
    descriptor = {**t.selection_asset(db, base), "root_knots": [[0, 0], [0.99999, 0.99999]]}
    legacy = t.register_asset(db, root["source_id"], descriptor, legacy_mapping=True)
    cropped = t.AssetSelection(legacy.asset_id, 0.1, 0.3)
    child = ops.save(db, cropped, title="有覆盖的子选区")
    assert ops.descendants(db, legacy)[0]["id"] == child["id"]
    assert suggest(db, root["source_id"], descriptor, 0, 1)
    assert t.selection_asset(db, legacy)["root_knots"] == descriptor["root_knots"]


def test_descendants_exclude_source_browser_across_assets(library):
    from ottosmasher.sample_ops import source_browser

    db, root, _ = library
    asset_migration.activate(db)
    browser = source_browser(db, root["source_id"])
    base = ops.from_sample(db, root["id"])
    descriptor = {**t.selection_asset(db, base), "role": "vocals"}
    alternate = t.register_asset(db, root["source_id"], descriptor, legacy_mapping=True)
    child = ops.save(db, t.AssetSelection(base.asset_id, 0.2, 0.6), title="子采样")
    result = ops.descendants(db, alternate, source=True)
    assert browser["id"] not in {r["id"] for r in result}
    assert child["id"] in {r["id"] for r in result}
    # A full-length user sample on the other asset must remain selectable.
    assert root["id"] in {r["id"] for r in result}


def test_reimport_duration_replaces_end_and_preserves_mapping_knots(library,tmp_path):
    db,root,_=library
    asset_migration.activate(db)
    original=ops.from_sample(db,root['id'])
    descriptor=t.selection_asset(db,original)
    descriptor['root_knots']=[[0,0],[.4,.6],[1,1]]
    asset=t.register_asset(db,root['source_id'],descriptor)
    selected=t.AssetSelection(asset.asset_id,.2,.3)
    path=tmp_path/'short.wav';sf.write(path,np.zeros(24000),48000)
    sel,parent,_,_=ops.import_range(db,selected,path)
    assert sel.end==pytest.approx(.7)
    assert parent['root_knots'][1]==pytest.approx([.2,.6])
    assert parent['root_knots'][0]==pytest.approx([0,.3])
    sf.write(path,np.zeros(2400),48000)
    assert ops.import_range(db,selected,path)[0].end==pytest.approx(.25)
    sf.write(path,np.zeros(38400),48000)
    assert ops.import_range(db,selected,path)[0].end==pytest.approx(1)
