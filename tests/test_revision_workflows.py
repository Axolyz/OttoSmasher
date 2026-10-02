import json
import sys
from types import SimpleNamespace
import numpy as np
import pytest
from test_samples import library
from ottosmasher import asset_timeline as t, asset_migration, selection_ops, track_roles
from ottosmasher import source_preparation as prep, subtitle_import as sub, materials


def test_tag_options_count_samples_not_inheritance_paths(monkeypatch):
    from ottosmasher import tag_management

    inherited = {"tag": "work:作品", "inherited": True, "origin": "source"}
    local = {"tag": "work:作品", "inherited": False, "origin": "manual"}
    monkeypatch.setattr(tag_management, "effective_all", lambda db, ids: {
        "first": [inherited, {**inherited, "origin": "annotation"}, local],
        "second": [inherited, inherited],
    })
    assert tag_management.options(None, ["first", "second"]) == [
        {"tag": "work:作品", "local": 1, "inherited": 2}
    ]


def prepare(db, root, tmp_path):
    asset_migration.activate(db)
    path = tmp_path / "captions.srt"
    path.write_text(
        "1\n00:00:00,100 --> 00:00:00,300\n（ドア）（足音）\n\n2\n00:00:00,350 --> 00:00:00,600\n（京子）こんにちは\n"
    )
    prep.configure(db, root["source_id"], subtitle_path=str(path), op_review="skipped")
    before = db.execute("SELECT count(*) FROM materials").fetchone()[0]
    prep.ingest(db, root["source_id"], prep.preview(db, root["source_id"])["token"])
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == before
    sel = selection_ops.from_sample(db, root["id"])
    track_roles.configure(db, root["source_id"], sel.asset_id, ["speech", "effects"], ["speech", "effects"])
    return sel


def test_subtitle_samples_are_explicit_deduplicated_and_scoped(library, tmp_path):
    from ottosmasher.ui_catalog import effective_all
    from ottosmasher.sample_deletion import remove

    db, root, _ = library
    sel = prepare(db, root, tmp_path)
    plan = sub.preview(db, root["source_id"], "event")
    assert len(plan["rows"]) == 1 and plan["rows"][0]["title"] == "ドア / 足音"
    assert plan["rows"][0]["start"] == 0 and plan["rows"][0]["end"] == pytest.approx(0.6)
    effect = sub.create(db, root["source_id"], "event", plan["token"])["sample_ids"][0]
    plan = sub.preview(db, root["source_id"], "dialogue")
    voice = sub.create(db, root["source_id"], "dialogue", plan["token"])["sample_ids"][0]
    assert materials.get(db, effect)["nature"] == "unpitched"
    assert materials.get(db, voice)["nature"] == "speech"
    assert not db.execute("SELECT 1 FROM material_tags WHERE material_id=?", (voice,)).fetchone()
    assert "character:京子" in {r["tag"] for r in effective_all(db, [voice])[voice]}
    remove(db, [voice])
    db.commit()
    materials.sync_cues(db)
    assert not db.execute("SELECT 1 FROM materials WHERE id=?", (voice,)).fetchone()
    assert sub.preview(db, root["source_id"], "dialogue")["rows"][0]["status"] == "imported"


def test_role_defaults_do_not_move_samples(library, tmp_path):
    db, root, _ = library
    sel = prepare(db, root, tmp_path)
    cut = selection_ops.save(db, sel, title="cut", nature="speech")
    other = t.register_asset(db, root["source_id"], {**t.selection_asset(db, sel), "role": "vocals"})
    track_roles.configure(db, root["source_id"], other.asset_id, ["speech"], ["speech"])
    assert t.sample_selection(db, cut["id"]).asset_id == sel.asset_id
    assert set(r[0] for r in db.execute("SELECT asset_id FROM asset_groups WHERE group_name='dialogue'")) >= {
        sel.asset_id,
        other.asset_id,
    }
    assert track_roles.default_asset(db, root["source_id"], "dialogue")["id"] == other.asset_id


def test_missing_track_and_stale_preview_rejected(library, tmp_path):
    db, root, _ = library
    sel = prepare(db, root, tmp_path)
    plan = sub.preview(db, root["source_id"], "event")
    track_roles.configure(db, root["source_id"], sel.asset_id, ["speech"], ["speech"])
    with pytest.raises(ValueError, match="默认音效轨"):
        sub.create(db, root["source_id"], "event", plan["token"])


def test_explicit_role_removal_survives_asset_reuse(library):
    db, root, _ = library
    asset_migration.activate(db)
    raw = selection_ops.from_sample(db, root["id"])
    descriptor = {**t.selection_asset(db, raw), "role": "vocals"}
    vocal = t.register_asset(db, root["source_id"], descriptor)
    track_roles.configure(db, root["source_id"], vocal.asset_id, ["effects"], ["effects"])
    assert t.register_asset(db, root["source_id"], descriptor).asset_id == vocal.asset_id
    assert track_roles.nature(db, vocal.asset_id) == "unpitched"


@pytest.mark.parametrize(
    "text,kind,title,speakers",
    [
        ("(足音)(扉)", "event", "足音 / 扉", []),
        ("（京子）こんにちは", "dialogue", "こんにちは", ["京子"]),
        ("台詞（結衣）続き", "dialogue", "台詞続き", ["結衣"]),
        ("(京子)(結衣)こんにちは", "dialogue", "こんにちは", ["京子", "結衣"]),
        ("普通の台詞", "dialogue", "普通の台詞", []),
    ],
)
def test_subtitle_rules(text, kind, title, speakers):
    assert sub.classify(text, {}) == {"kind": kind, "title": title, "speakers": speakers}


def test_regex_timeout_and_invalid_capture():
    with pytest.raises(ValueError):
        sub.classify("(x)", {"subtitle_bracket_pattern": "(.)"})
    with pytest.raises(ValueError):
        sub.classify("a" * 100000 + "!", {"subtitle_event_pattern": "(a+)+$"})


def test_acoustic_bounds_preserve_measurements_and_manual():
    from ottosmasher.vowel_bounds import annotate, bounds

    times = np.arange(0.005, 1, 0.01)
    energy = np.where((times >= 0.2) & (times < 0.7), 0.01, 0)
    phones = [
        {"label": "a", "start": 0, "end": 1},
        {"label": "N", "start": 0, "end": 1},
        {"label": "n", "start": 0, "end": 1},
    ]
    annotate(phones, {"times": times, "energy": energy})
    assert phones[0]["start"] == 0 and phones[0]["end"] == 1
    assert phones[0]["effective_start"] == pytest.approx(0.19)
    assert phones[1]["effective_end"] == pytest.approx(0.71)
    assert "effective_start" not in phones[2]
    assert bounds(0, 1, times, energy, manual=True) == [0, 1]
    assert bounds(0, 1, times, np.zeros(100)) == [0, 1]


def test_acceleration_policy_and_no_silent_fallback(monkeypatch):
    from ottosmasher import inference_runtime as runtime

    options = SimpleNamespace()

    class Session:
        def __init__(self, *args, **kwargs):
            self.providers = ["CPUExecutionProvider"]

        def disable_fallback(self):
            pass

        def get_providers(self):
            return self.providers

    ort = SimpleNamespace(
        get_available_providers=lambda: ["DmlExecutionProvider", "CPUExecutionProvider"],
        SessionOptions=lambda: options,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="serial"),
        InferenceSession=Session,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    assert runtime.onnx_providers({}) == ["CPUExecutionProvider"]
    with pytest.raises(RuntimeError, match="未回退"):
        runtime.onnx_session(b"model", config={"onnx_acceleration": True})
    assert options.enable_mem_pattern is False and options.execution_mode == "serial"


def test_relocation_keeps_id_clock_and_measurement(library, tmp_path):
    from ottosmasher.source_locations import relocate

    db, root, _ = library
    asset_migration.activate(db)
    sel = selection_ops.from_sample(db, root["id"])
    old = t.selection_asset(db, sel)
    target = tmp_path / "moved.wav"
    target.write_bytes(b"not verified intentionally")
    result = relocate(db, root["source_id"], target)
    current = t.selection_asset(db, sel)
    assert result["identity_verified"] is False
    assert current["path"] == str(target) and current["sha256"] == old["sha256"]
    assert current["root_knots"] == old["root_knots"]


def test_tag_edits_are_previewed_and_undoable(library):
    from ottosmasher import tag_management, business_edits

    db, root, _ = library
    asset_migration.activate(db)
    plan = tag_management.plan(db, [root["id"]], ["新标签"])
    db.commit()
    result = business_edits.apply(db, plan["document"])
    assert result["valid"]
    assert db.execute("SELECT 1 FROM material_tags WHERE tag='新标签'").fetchone()
    plan = tag_management.plan(db, [root["id"]], ["新标签"], "remove")
    db.commit()
    result = business_edits.apply(db, plan["document"])
    assert not db.execute("SELECT 1 FROM material_tags WHERE tag='新标签'").fetchone()


def import_dialogue(db, root):
    """Test helper exercising the explicit role/preview/create workflow."""
    asset_migration.activate(db)
    sel = selection_ops.from_sample(db, root["id"])
    track_roles.configure(db, root["source_id"], sel.asset_id, ["speech"], ["speech"])
    p = sub.preview(db, root["source_id"], "dialogue")
    return sub.create(db, root["source_id"], "dialogue", p["token"])["sample_ids"]


def test_partial_markers_keep_saved_rules(library, tmp_path):
    db, root, _ = library
    asset_migration.activate(db)
    path = tmp_path / "partial.srt"
    path.write_text(
        "1\n00:00:00,000 --> 00:00:00,200\n(A)first\n\n2\n00:00:00,300 --> 00:00:00,500\n(B)second\n"
    )
    prep.configure(db, root["source_id"], subtitle_path=str(path), op_review="skipped")
    token = prep.preview(db, root["source_id"])["token"]
    prep.ingest(db, root["source_id"], token, ordinals=[0])
    assert db.execute("SELECT count(*) FROM timeline_annotations").fetchone()[0] == 1
    assert len(import_dialogue(db, root)) == 1
    prep.ingest(db, root["source_id"], token, ordinals=[1])
    assert len(import_dialogue(db, root)) == 1
    assert len(import_dialogue(db, root)) == 0
    assert db.execute("SELECT count(*) FROM timeline_annotations").fetchone()[0] == 2


def test_fixed_result_ids_and_star_refresh(library, monkeypatch):
    from contextlib import contextmanager
    from ottosmasher import search_sessions, library_tools_api, sample_catalog

    db, root, _ = library
    asset_migration.activate(db)
    other = selection_ops.save(db, selection_ops.from_sample(db, root["id"]), title="other")
    rows = [{"id": root["id"], "title": "old", "starred": False, "hits": []} for _ in range(101)] + [
        {"id": other["id"], "hits": []}
    ]
    session = search_sessions.create(db, "speech", {}, {"results": rows})["id"]

    @contextmanager
    def database():
        yield db

    monkeypatch.setattr(library_tools_api, "database", database)
    sample_catalog.preferences(db, root["id"], starred=True)
    assert search_sessions.read(db, session)["results"][0]["starred"] is True
    assert library_tools_api.result_ids(session)["ids"] == [root["id"], other["id"]]
    from ottosmasher.sample_deletion import remove

    remove(db, [other["id"]])
    db.commit()
    assert library_tools_api.result_ids(session)["ids"] == [root["id"]]


def test_filters_intersect_and_tags_global_undo(library):
    from ottosmasher import tag_management, business_edits, sample_scope

    db, root, _ = library
    asset_migration.activate(db)
    db.execute("UPDATE source_labels SET work='作品' WHERE source_id=?", (root["source_id"],))
    db.commit()
    assert sample_scope.ids(db, {"intersections": [{"work": "作品"}, {"nature": "pitched"}]}) == []
    plan = tag_management.plan(
        db, tags=["work:作品"], operation="rename", replacement="work:新作品", global_scope=True
    )
    assert plan["tag_counts"] == {"work:作品": 1}
    db.commit()
    applied = business_edits.apply(db, plan["document"])
    assert applied["valid"]
    assert sample_scope.ids(db, {"work": "新作品"}) == [root["id"]]
    db.commit()
    business_edits.undo(db, applied["action_id"])
    assert sample_scope.ids(db, {"work": "作品"}) == [root["id"]]


def test_relocation_resolves_saved_playback_and_registration(library, tmp_path):
    from ottosmasher import source_locations, sample_audio
    import shutil

    db, root, _ = library
    asset_migration.activate(db)
    sel = selection_ops.from_sample(db, root["id"])
    old = t.selection_asset(db, sel)
    target = tmp_path / "renamed.wav"
    shutil.copyfile(old["path"], target)
    source_locations.relocate(db, root["source_id"], target)
    resolved = sample_audio.resolve(db, root["id"])
    assert resolved["path"] == str(target)
    assert t.register_asset(db, root["source_id"], resolved).asset_id == sel.asset_id
    assert source_locations.identity_descriptor(db, resolved) == old


def test_runtime_build_guard_rejects_torch_and_weight(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("stage_app", "scripts/stage_app.py")
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    weight = tmp_path / "model.onnx"
    weight.write_bytes(b"test")
    with pytest.raises(ValueError, match="权重"):
        stage.audit_software(tmp_path)
    (tmp_path / "lib/python/site-packages/torch").mkdir(parents=True)
    with pytest.raises(ValueError, match="PyTorch"):
        stage.audit_runtime(tmp_path)


def test_studio_platform_resource_layout(tmp_path):
    from ottosmasher.studio import resources_for, detect_app

    mac = tmp_path / "Studio.app"
    (mac / "Contents/Resources/python").mkdir(parents=True)
    (mac / "Contents/Resources/python/worker.py").touch()
    win = tmp_path / "Studio"
    (win / "resources/python").mkdir(parents=True)
    (win / "resources/python/worker.py").touch()
    assert resources_for(mac) == mac / "Contents/Resources"
    assert resources_for(win / "Studio.exe") == win / "resources"
    assert detect_app(str(win)) == win


def test_subtitle_registration_failure_rolls_back_sample_and_dedup(library, tmp_path, monkeypatch):
    db, root, _ = library
    prepare(db, root, tmp_path)
    plan = sub.preview(db, root["source_id"], "dialogue")
    before = db.execute("SELECT count(*) FROM materials").fetchone()[0]
    original = selection_ops.save

    def fail_after_save(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure after sample insert")

    monkeypatch.setattr(selection_ops, "save", fail_after_save)
    with pytest.raises(RuntimeError, match="injected failure"):
        sub.create(db, root["source_id"], "dialogue", plan["token"])
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == before
    assert db.execute("SELECT count(*) FROM subtitle_sample_imports").fetchone()[0] == 0
    assert sub.preview(db, root["source_id"], "dialogue")["rows"][0]["status"] == "ready"


def test_folder_retirement_preserves_legacy_facts_and_batch_identity(library):
    from ottosmasher import sample_catalog as catalog

    db, root, _ = library
    batch = catalog.batch(db, {"query": "old"})
    child = catalog.derive(db, root["id"], start=0.1, end=0.5, batch_id=batch["id"], nature="speech")
    db.execute("ALTER TABLE materials ADD COLUMN folder_id TEXT DEFAULT 'custom'")
    db.execute("CREATE TABLE sample_folders(id TEXT PRIMARY KEY,name TEXT,batch_id TEXT)")
    db.execute("INSERT INTO sample_folders VALUES('custom','User folder',NULL)")
    db.execute("ALTER TABLE sample_batches ADD COLUMN folder_id TEXT DEFAULT 'custom'")
    db.execute("ALTER TABLE sample_batches ADD COLUMN target_folder TEXT DEFAULT 'custom'")
    db.execute("CREATE TABLE saved_views(id TEXT PRIMARY KEY,name TEXT,payload TEXT)")
    db.execute(
        "INSERT INTO saved_views VALUES('v','filter',?)",
        (
            json.dumps(
                {
                    "folder_id": "custom",
                    "nature": "speech",
                    "intersections": [{"folder_ids": ["custom"], "starred": True}],
                }
            ),
        ),
    )
    snapshots = {
        table: [tuple(r) for r in db.execute("SELECT * FROM " + table)]
        for table in ("sample_edges", "sample_batch_items", "material_tags", "analysis_runs")
    }
    facts = [tuple(r) for r in db.execute("SELECT id,nature,status,pool FROM materials ORDER BY id")]
    catalog.retire_folders(db)
    assert "folder_id" not in {r[1] for r in db.execute("PRAGMA table_info(materials)")}
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='sample_folders'").fetchone()
    assert db.execute("SELECT id FROM sample_batches").fetchone()[0] == batch["id"]
    assert facts == [tuple(r) for r in db.execute("SELECT id,nature,status,pool FROM materials ORDER BY id")]
    for table, rows in snapshots.items():
        assert [tuple(r) for r in db.execute("SELECT * FROM " + table)] == rows
    assert json.loads(db.execute("SELECT payload FROM saved_views").fetchone()[0]) == {
        "nature": "speech",
        "intersections": [{"starred": True}],
    }
    catalog.retire_folders(db)  # Repeated startup is a no-op.


def test_relocating_back_to_prior_path_keeps_original_asset_identity(library, tmp_path):
    from ottosmasher import source_locations
    import shutil

    db, root, _ = library
    asset_migration.activate(db)
    selected = selection_ops.from_sample(db, root["id"])
    original = t.selection_asset(db, selected)
    target = tmp_path / "second.wav"
    shutil.copyfile(original["path"], target)
    for destination in (target, original["path"], target):
        source_locations.relocate(db, root["source_id"], destination)
        current = t.selection_asset(db, selected)
        assert source_locations.identity_descriptor(db, current) == original
        assert t.register_asset(db, root["source_id"], current).asset_id == selected.asset_id


def test_missing_runtime_still_reports_model_files(monkeypatch, tmp_path):
    from ottosmasher import inference_runtime as runtime, model_inventory

    model = tmp_path / "models/narabas/narabas-v0.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"file presence only, not an inference test")
    monkeypatch.setattr(model_inventory, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "python_path", lambda: tmp_path / "missing-python")
    monkeypatch.setattr(runtime, "settings", lambda: {"onnx_acceleration": False})
    result = runtime.check()
    assert not result["ready"]
    assert result["models"][0]["files_ready"]
    assert result["models"][0]["inference_status"] == "未实测"
    assert not result["models"][1]["files_ready"]


def test_jobs_freeze_device_settings_before_later_changes(library, monkeypatch, tmp_path):
    from ottosmasher import operation_jobs, ui_catalog, job_worker, opening_scan, inference_runtime

    db, root, _ = library
    monkeypatch.setenv("OTTO_EDITION", "standard")
    monkeypatch.setenv("OTTO_ARCHIVED", "")
    monkeypatch.delenv("OTTO_INFERENCE_SETTINGS", raising=False)
    monkeypatch.setattr(operation_jobs, "DATA", tmp_path / "data")
    monkeypatch.setattr(operation_jobs, "launch", lambda jid: {"id": jid})
    ui_catalog.settings(db, {"onnx_acceleration": True, "onnx_device_id": 2})
    job = operation_jobs._submit("opening-scan", {"source_id": root["source_id"]})
    payload = json.loads(
        db.execute("SELECT payload FROM operation_jobs WHERE id=?", (job["id"],)).fetchone()[0]
    )
    ui_catalog.settings(db, {"onnx_acceleration": False, "onnx_device_id": 0})
    monkeypatch.setattr(opening_scan, "run", lambda *_: inference_runtime.settings())
    observed = job_worker.run("opening-scan", payload, job["id"])
    assert observed["onnx_acceleration"] is True
    assert observed["onnx_device_id"] == 2
