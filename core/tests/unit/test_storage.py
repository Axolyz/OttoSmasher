"""存储与缓存（规格 13 §13.3.3–§13.3.4、16 R20.4–R20.5、S12.4）：只删可清理的缓存；15 分钟内的不删；不跟随符号链接；有任务时拒绝手动清理；
空闲自动整理：1 天以上的删、超过 512 MiB 删到 384 MiB；永不当缓存删的（测量、素材库）不碰。"""

from __future__ import annotations

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
    from ottosmasher.core.job_artifacts import cleanup_separation
    jobs = tmp_path / 'jobs'
    outside = make(tmp_path / 'outside' / 'input' / 'audio.wav')
    jobs.mkdir()
    (jobs / 'linked').symlink_to(outside.parent.parent)
    cleanup_separation(jobs, 'linked')
    cleanup_separation(jobs, '../outside')
    (jobs / 'real').mkdir()
    (jobs / 'real' / 'input').symlink_to(outside.parent)
    cleanup_separation(jobs, 'real')
    assert outside.exists()
