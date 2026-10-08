"""F0 测量存储（规格 10 §10.1）：60 秒分段、只测用到的段、逐帧无损、没测的帧为 NaN。"""

from __future__ import annotations

import numpy as np
import pytest

from ottosmasher.models import f0store


def test_chunks_and_plan():
    assert f0store.chunks_for(1.0, 2.0, 1436.4) == [0]
    assert f0store.chunks_for(59.5, 60.5, 1436.4) == [0, 1]
    assert f0store.chunks_for(1430.0, 1436.4, 1436.4) == [23]
    p0 = f0store.chunk_plan(0, 1436.4)
    assert p0 == {"decode": [0.0, 61.0], "skip": 0, "frames": 6000}
    p1 = f0store.chunk_plan(1, 1436.4)
    assert p1["decode"] == [59.0, 121.0] and p1["skip"] == 100 and p1["frames"] == 6000
    last = f0store.chunk_plan(23, 1436.4)
    assert last["frames"] == f0store.total_frames(1436.4) - 23 * 6000 and last["decode"][1] == 1436.4


def test_identity_depends_on_audio_and_model():
    a = {"asset": "x", "snapshot": {"size": 1, "mtime_ns": 2}}
    assert f0store.identity(a, "m") == f0store.identity(dict(a), "m")
    assert f0store.identity({**a, "snapshot": {"size": 2, "mtime_ns": 2}}, "m") != f0store.identity(a, "m")
    assert f0store.identity(a, "n") != f0store.identity(a, "m")


def test_adopt_and_read(tmp_path):
    root = tmp_path / "f0"
    src = tmp_path / "1.npy"
    arr = np.arange(6000 * 3, dtype=np.float32).reshape(6000, 3)
    np.save(src, arr)
    f0store.adopt_chunk(root, "A", "id1", 1, src, {"m": 1})
    assert f0store.present(root, "A", "id1") == {1}
    i0, frames, have = f0store.read(root, "A", "id1", 59.99, 60.03, 200.0)
    assert i0 == 5999 and len(frames) == 4
    assert not have[0] and np.isnan(frames[0]).all()
    assert have[1:].all() and frames[1].tolist() == arr[0].tolist() and frames[3].tolist() == arr[2].tolist()
    # 再次放入同一段不覆盖
    np.save(src, arr * 0)
    f0store.adopt_chunk(root, "A", "id1", 1, src, {"m": 1})
    assert f0store.read(root, "A", "id1", 60.0, 60.01, 200.0)[1][0].tolist() == pytest.approx(arr[0].tolist())
