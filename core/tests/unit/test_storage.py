"""存储与缓存（规格 13 §13.3.3–§13.3.4、16 R20.4–R20.5、S12.4）：只删可清理的缓存；15 分钟内的不删；不跟随符号链接；有任务时拒绝手动清理；
空闲自动整理：1 天以上的删、超过 512 MiB 删到 384 MiB；永不当缓存删的（测量、素材库）不碰。"""

from __future__ import annotations

import json
import os
import time

import pytest

from ottosmasher.core import storage as st
from ottosmasher.core.errors import CoreError
from ottosmasher.core.storage import StorageService


class Jobs:
    pass


def make(p, size=10, age=0.0):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


def test_manual_clean_and_protection(db, ws, tmp_path):
    svc = StorageService(db, ws, Jobs())
    old = make(ws.data / "Cache" / "Peaks" / "a.bin", 100, age=3600)
    recent = make(ws.data / "Cache" / "Thumbs" / "b.jpg", 50, age=60)
    stale_tmp = make(ws.staging / "x.wav", 20, age=7200)
    keep_f0 = make(ws.data / "Measurements" / "f0" / "a" / "0.npy", 30, age=99999)
    keep_lib = make(ws.library / "Tracks" / "s [abcd1234]" / "Separation" / "v.mp3", 30, age=99999)
    outside = make(tmp_path / "outside.txt", 5, age=99999)
    (ws.data / "Cache" / "link").symlink_to(tmp_path)  # 指向外面的目录：不跟随
    rep = {c["key"]: c for c in svc.report()["categories"]}
    assert rep["cache"]["recent"] == 1 and rep["cache"]["cleanable"] == 120 and rep["measurements"]["cleanable"] == 0
    out = svc.clean()
    assert out["files"] == 2 and out["bytes"] == 120
    assert not old.exists() and not stale_tmp.exists() and recent.exists()
    assert keep_f0.exists() and keep_lib.exists() and outside.exists()
    # 有任务排队 / 运行时拒绝
    db.execute("INSERT INTO job(id, kind, channel, status, params, device, created_at) VALUES ('j', 'x', 'light', 'running', '{}', '{}', '2026-01-01')")
    with pytest.raises(CoreError) as ei:
        svc.clean()
    assert ei.value.code == "storage-busy"
    assert svc.tick() is None  # 自动整理也等任务结束


def test_idle_auto_cleanup_watermarks(db, ws, monkeypatch):
    monkeypatch.setattr(st, "HIGH", 1000)
    monkeypatch.setattr(st, "LOW", 600)
    svc = StorageService(db, ws, Jobs())
    day_old = make(ws.data / "Cache" / "old.bin", 100, age=2 * 86400)
    files = [make(ws.data / "Cache" / f"f{i}.bin", 200, age=3600 * (10 - i)) for i in range(6)]  # 1200 字节，都不到 1 天
    assert svc.tick() is None  # 刚有过输入：不算空闲
    svc.last_input = time.time() - 6 * 60
    r = svc.tick()
    assert r is not None and not day_old.exists()
    left = sum(p.stat().st_size for p in files if p.exists())
    assert left <= 600 and files[-1].exists() and not files[0].exists()  # 从最旧的删到低水位以下
    assert svc.tick() is None  # 一小时内不再整理


def test_successful_separation_leftovers_are_cleanable_but_evidence_is_not(db, ws, tmp_path):
    svc = StorageService(db, ws, Jobs())
    for jid, kind, status in [('ok', 'separate', 'succeeded'), ('bad', 'separate', 'failed'),
                              ('cancel', 'separate', 'cancelled'), ('other', 'speech.analyze', 'succeeded')]:
        db.execute("INSERT INTO job(id,kind,channel,status,params,device,created_at) VALUES (?,?,'model',?,'{}','{}','2026-01-01')",
                   (jid, kind, status))
    gone = [make(ws.jobs / 'ok' / directory / 'audio.wav', 100, age=3600) for directory in ('input', 'out', 'tracks')]
    keep = [make(ws.jobs / jid / 'input' / 'input.wav', 100, age=3600) for jid in ('bad', 'cancel', 'other')]
    keep += [make(ws.jobs / 'ok' / name, 10, age=3600) for name in ('log.txt', 'studio.log', 'input.json', 'result.json')]
    keep.append(make(ws.jobs / 'ok' / 'out' / 'recent.wav', 10, age=60))
    outside = make(tmp_path / 'outside' / 'audio.wav', 100, age=3600)
    (ws.jobs / 'ok' / 'out' / 'linked').symlink_to(outside.parent)
    (ws.jobs / 'ok' / 'out' / 'link.wav').symlink_to(outside)
    rep = {r['key']: r for r in svc.report()['categories']}
    assert rep['jobs']['cleanable'] == 300 and rep['jobs']['recent'] == 1
    assert rep['cache']['cleanable'] == 0
    result = svc.clean()
    assert result['bytes'] == 300
    assert all(not p.exists() for p in gone)
    assert all(p.exists() for p in keep) and outside.exists()


def test_private_cleanup_refuses_job_or_directory_symlinks(tmp_path):
    from ottosmasher.jobs.artifacts import cleanup_intermediates
    jobs = tmp_path / 'jobs'
    outside = make(tmp_path / 'outside' / 'input' / 'audio.wav')
    jobs.mkdir()
    (jobs / 'linked').symlink_to(outside.parent.parent)
    (jobs / 'real').mkdir()
    (jobs / 'real' / 'input').symlink_to(outside.parent)
    for jid in ('linked', '../outside', 'real'):
        cleanup_intermediates(jobs, jid, 'separate', tmp_path / 'f0', ())
    assert outside.exists()


def test_only_identical_adopted_f0_and_private_cache_are_cleaned(db, ws):
    svc = StorageService(db, ws, Jobs())
    plan = json.dumps({"plan": [{"asset": "asset", "identity": "original", "chunks": [0, 1, 2, 3]}]})
    db.execute("INSERT INTO job(id,kind,channel,status,params,device,created_at) VALUES ('done','f0.measure','model','succeeded',?,'{}','2026-01-01')", (plan,))
    job = ws.jobs / "done"
    formal = ws.f0 / "asset" / "original"
    make(formal / "0.npy", age=3600)
    make(formal / "1.npy", age=3600).write_bytes(b"y" * 10)
    make(formal / "3.npy", age=3600)
    (formal / "manifest.json").write_text('{"chunks":{"0":{},"1":{},"2":{},"3":{}}}')
    copies = [make(job / "f0" / "asset" / f"{i}.npy", age=60 if i == 3 else 3600) for i in range(4)]
    cache = make(job / "cache" / "FrameIndex" / "index.npz", age=3600)
    result = svc.clean()
    assert result == {"files": 2, "bytes": 20, "rows": 0}
    assert not copies[0].exists() and not cache.exists()
    assert all(p.exists() for p in copies[1:])
    assert (formal / "0.npy").read_bytes() == b"x" * 10


def test_clean_old_job_history_keeps_retry_ancestors_and_recovers_file_removal(db, ws, monkeypatch):
    svc = StorageService(db, ws, Jobs())
    for jid, ts, retry in [
        ("origin", "2000-01-01", None), ("retry", "2000-01-01", "origin"), ("recent", "2099-01-01", "retry"),
        ("gone", "2000-01-01", None), ("gone_retry", "2000-01-01", "gone"),
    ]:
        db.execute("INSERT INTO job(id,kind,channel,status,params,device,created_at,retry_of) VALUES (?, 'speech.align','model','failed','{}','{}',?,?)", (jid, ts, retry))
        db.execute("INSERT INTO job_item(job_id,idx,target,status) VALUES (?,0,'x','failed')", (jid,))
        make(ws.jobs / jid / "log.txt")
    assert svc.history_preview() == {"days": 90, "count": 2}
    db.execute("UPDATE job SET status='running' WHERE id='recent'")
    with pytest.raises(CoreError, match="storage-busy"):
        svc.clean_job_history()
    db.execute("UPDATE job SET status='failed' WHERE id='recent'")
    def unavailable(_path):
        raise PermissionError("test file lock")
    with monkeypatch.context() as m:
        m.setattr(st.shutil, "rmtree", unavailable)
        assert svc.clean_job_history() == {"files": 0, "bytes": 0, "rows": 2}
    assert {r[0] for r in db.execute("SELECT job_id FROM job_item")} == {"origin", "retry", "recent"}
    assert (ws.jobs / "gone" / "log.txt").is_file()
    assert svc.clean()["bytes"] == 20
    assert not (ws.jobs / "gone").exists() and not (ws.jobs / "gone_retry").exists()
    assert (ws.jobs / "origin" / "log.txt").is_file()


def test_old_alignment_results_are_packed_and_can_still_be_paged(db, ws):
    from ottosmasher.jobs.artifacts import RESULTS_ARCHIVE, alignment_items

    svc = StorageService(db, ws, Jobs())
    db.execute("INSERT INTO job(id,kind,channel,status,params,device,created_at) VALUES ('align','speech.align','model','succeeded','{}','{}','2026-01-01')")
    job = ws.jobs / "align"
    for i in (0, 31, 32, 65):
        make(job / "items" / f"{i}.json", 400, age=3600)
    assert alignment_items(job, [31, 32, 33]) == {31: b"x" * 400, 32: b"x" * 400}
    result = svc.clean()
    assert result["files"] == 4 and result["bytes"] > 0
    assert (job / RESULTS_ARCHIVE).is_file() and not list((job / "items").iterdir())
    assert alignment_items(job, [31, 32, 33]) == {31: b"x" * 400, 32: b"x" * 400}
    assert svc.clean() == {"files": 0, "bytes": 0, "rows": 0}
