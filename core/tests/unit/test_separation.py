"""分离：规格 05 §5.5、14 §14.6、13 §13.3.2；16 R18.1–R18.6、R2.5（伪 Studio + 合成音频）。"""

import subprocess

import pytest

from fake_studio import make_fake_studio
from ottosmasher.core import assets as assets_mod
from ottosmasher.core.errors import CoreError
from ottosmasher.core.samples import SampleService
from ottosmasher.core.separation import SeparationService
from ottosmasher.core.sources import SourceService
from ottosmasher.media import mp3
from ottosmasher.studio import discovery
from test_scheduler import Harness


@pytest.fixture
def env(db, ws, tmp_path):
    h = Harness(db, ws)
    app, data = make_fake_studio(tmp_path / "studio")
    h.set("studio.app_path", app)
    h.set("studio.data_dir", data)
    wav = tmp_path / "src [01].wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:duration=3", "-ac", "2", "-c:a", "pcm_s16le", str(wav)],
        check=True,
    )
    sources = SourceService(db, workspace_root=ws.root)
    sid = sources.add([str(wav)])[0]["sourceId"]
    aid = assets_mod.list_for_source(db, sid)[0]["id"]
    svc = SeparationService(db, ws, h.s, samples=SampleService(db))
    yield h, svc, sid, aid, data
    h.cleanup()


def list_models(h, svc):
    st = svc.status()
    assert st["ok"] and st["models"] is None
    h.wait_status(st["listingJob"], "succeeded")
    st = svc.status()
    assert st["listingJob"] is None
    return st["models"]


def test_discovery_errors(tmp_path):
    with pytest.raises(CoreError) as e:
        discovery.discover(str(tmp_path / "nope.app"))
    assert e.value.code == "studio-not-found"
    app, data = make_fake_studio(tmp_path / "s")
    (tmp_path / "s" / "data" / "runtime-envs" / "active-runtime.json").unlink()
    with pytest.raises(CoreError) as e:
        discovery.discover(app, data)
    assert e.value.code == "studio-no-runtime"


def test_models_are_filtered_and_classified(env):
    h, svc, *_ = env
    models = {m["name"]: m for m in list_models(h, svc)}
    assert set(models) == {"fake_vocals", "fake_3track"}  # 未下载完整、不支持的不列
    assert (models["fake_vocals"]["stems"], models["fake_vocals"]["vocal"], models["fake_vocals"]["threeTrack"]) == (["Vocals", "Instrumental"], True, False)
    assert (models["fake_3track"]["vocal"], models["fake_3track"]["threeTrack"]) == (False, True)


def test_full_separation_registers_stems_and_reuses(db, ws, env):
    h, svc, sid, aid, _ = env
    list_models(h, svc)
    job = svc.submit(aid, None, None, "fake_vocals.ckpt", None)["job"]  # 按别名找模型
    h.wait_status(job["id"], "succeeded", "failed", timeout=60)
    assert h.status(job["id"]) == "succeeded", h.s.summary(job["id"])["error"]
    created = svc.results(job["id"])
    by_stem = {a["stem_name"]: a for a in created}
    assert set(by_stem) == {"Vocals", "Instrumental"}  # 声部名保留 Studio 原样
    v = by_stem["Vocals"]
    assert (v["origin"], v["input_asset_id"], v["input_start"], v["input_end"]) == ("separation", aid, 0.0, 3.0)
    assert v["mapping"] == [[0.0, 0.0], [3.0, 3.0]]
    assert v["roles"] == ["vocal"] and by_stem["Instrumental"]["roles"] == []  # 别名表预填（不分大小写）
    assert db.execute("SELECT COUNT(*) FROM default_track").fetchone()[0] == 0  # 不自动设默认轨
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0  # 整轨分离是原素材的音轨：不建采样
    assert v["production"]["model"] == "fake_vocals" and v["production"]["studioVersion"] == "9.9.9"
    mf = db.execute("SELECT path, location, format, frames, sample_rate FROM media_file WHERE id=?", (v["media_file_id"],)).fetchone()
    assert (mf["location"], mf["format"], mf["frames"], mf["sample_rate"]) == ("library", "mp3", 144000, 48000)
    path = ws.root / mf["path"]
    # L23：Library/Tracks/<作品 集数> [id8]/Separation/
    assert path.is_file() and mf["path"].startswith("Library/Tracks/") and f"[{sid[:8]}]/Separation/" in mf["path"]
    assert 0 <= mp3.decoded_frames(path, 2) - 144000 <= 1152  # 无缝
    private = ws.jobs / job["id"]
    assert (private / "input.json").exists() and (private / "log.txt").exists()
    assert not list((private / "input").rglob("*.wav"))
    assert not list((private / "out").rglob("*.wav"))
    assert not list((private / "tracks").rglob("*.mp3"))
    # 复用：同一输入 + 同一模型 + 所需声部都在 → 不重跑
    r = svc.submit(aid, None, None, "fake_vocals", ["Vocals"])
    assert r == {"reused": [v["id"]]}


def test_selection_three_track_crops_mapping(db, env):
    h, svc, sid, aid, _ = env
    list_models(h, svc)
    job = svc.submit(aid, 0.5, 2.0, "fake_3track", ["speech", "effects"])["job"]
    h.wait_status(job["id"], "succeeded", "failed", timeout=60)
    assert h.status(job["id"]) == "succeeded", h.s.summary(job["id"])["error"]
    got = {a["stem_name"]: a for a in svc.results(job["id"])}
    assert set(got) == {"speech", "effects"}
    assert got["speech"]["mapping"] == [[0.0, 0.5], [1.5, 2.0]]
    assert (got["speech"]["roles"], got["effects"]["roles"]) == (["vocal"], ["sfx"])
    # 局部分离（对选区）自动建采样，每个声部一个（所有者 2026-10-13）：整段、名称 = 建议名 · 声部、性质按角色
    rows = {r["asset_id"]: r for r in db.execute('SELECT asset_id, start, "end", name, nature, created_via FROM sample')}
    sp, ef = rows[got["speech"]["id"]], rows[got["effects"]["id"]]
    assert (sp["start"], sp["end"], sp["nature"], sp["created_via"]) == (0.0, 1.5, "speech", "processed") and sp["name"].endswith("\u00b7 speech")
    assert ef["nature"] == "unpitched" and len(rows) == 2
    with pytest.raises(CoreError) as e:
        svc.submit(aid, None, None, "fake_3track", ["Vocals"])
    assert e.value.code == "sep-stems-invalid"
    with pytest.raises(CoreError) as e:
        svc.submit(aid, None, None, "half_downloaded", None)
    assert e.value.code == "studio-model-missing"


@pytest.mark.parametrize(
    "mode,code",
    [("short", "sep-output-invalid"), ("missing", "sep-output-invalid"), ("error", "studio-failed"), ("exit1", "studio-failed"),
     ("touch", "sep-model-changed"), ("outside", "sep-output-invalid")],
)  # fmt: skip
def test_failures_register_nothing(db, ws, env, mode, code):
    h, svc, sid, aid, data = env
    list_models(h, svc)
    (__import__("pathlib").Path(data) / "mode.txt").write_text(mode)
    job = svc.submit(aid, None, None, "fake_vocals", None)["job"]
    h.wait_status(job["id"], "succeeded", "failed", timeout=60)
    s = h.s.summary(job["id"])
    assert s["status"] == "failed" and s["error"]["code"] == code, s
    assert db.execute("SELECT COUNT(*) FROM sound_asset WHERE origin='separation'").fetchone()[0] == 0
    assert not list((ws.root / "Library" / "Tracks").rglob("*.mp3"))
    assert (ws.jobs / job["id"] / "input" / "input.wav").exists()  # Failure evidence is retained.


def test_cancel_kills_studio_and_registers_nothing(db, ws, env):
    import os
    import time
    from pathlib import Path

    h, svc, sid, aid, data = env
    list_models(h, svc)
    (Path(data) / "mode.txt").write_text("slow")
    job = svc.submit(aid, None, None, "fake_vocals", None)["job"]
    pid_file = Path(data) / "studio-pid.txt"
    h.pump_until(pid_file.exists, timeout=30)
    pid = int(pid_file.read_text())
    h.s.cancel(job["id"])
    h.wait_status(job["id"], "cancelled", timeout=30)
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # Studio 子进程也结束了（进程树）
    assert db.execute("SELECT COUNT(*) FROM sound_asset WHERE origin='separation'").fetchone()[0] == 0


def test_failed_adoption_keeps_private_files(db, ws, env):
    h, svc, sid, aid, _ = env
    list_models(h, svc)
    def reject(_job, _result):
        raise CoreError('sep-output-invalid', reason='synthetic-adoption-failure')
    h.s.adopters['separate'] = reject
    job = svc.submit(aid, None, None, 'fake_vocals', ['Vocals'])['job']
    h.wait_status(job['id'], 'failed', timeout=60)
    assert (ws.jobs / job['id'] / 'input' / 'input.wav').exists()
    assert list((ws.jobs / job['id'] / 'tracks').glob('*.mp3'))
    assert not svc.results(job['id'])
