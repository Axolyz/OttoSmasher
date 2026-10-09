"""单音声学指标（规格 10 §10.3，16 R16）。"""

from __future__ import annotations

import numpy as np
import pytest

from ottosmasher.algo import acoustic as ac

SR = 48000


def tone(freqs_amps: list[tuple[float, float]], seconds: float = 0.6, attack: float = 0.02, release: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    x = sum(a * np.sin(2 * np.pi * f * t) for f, a in freqs_amps)
    env = np.minimum(1.0, t / attack) * np.clip((seconds - t) / release, 0, 1)
    return (x * env).astype(np.float64)


def f0_frames(hz: float | None, seconds: float = 0.6) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = int(round(seconds / 0.01))
    f0 = np.full(n, hz or 0.0)
    conf = np.full(n, 0.9 if hz else 0.0)
    en = np.full(n, 1e-3)
    return f0, conf, en, np.ones(n, dtype=bool)


def test_high_harmonics_gain_invariance_and_unknowns():
    base = ac.metrics(tone([(440, 0.5)]), SR, *f0_frames(440))
    more = ac.metrics(tone([(440, 0.5), (2640, 0.3)]), SR, *f0_frames(440))
    assert more["highHarmonicRatio"] - base["highHarmonicRatio"] >= 0.1  # R16.1：加入 2640 Hz（第 6 次谐波）
    assert base["pitch"] == pytest.approx(69.0, abs=0.01) and base["pitchSpread"] == pytest.approx(0.0, abs=1e-6)
    assert base["harmonicRatio"] > 0.9
    quiet = ac.metrics(0.1 * tone([(440, 0.5), (2640, 0.3)]), SR, *f0_frames(440))
    for k in ("lowRatio", "midRatio", "highRatio", "centroid", "flatness", "crestDb", "harmonicRatio", "highHarmonicRatio", "effectiveDuration", "attackTime"):
        assert quiet[k] == pytest.approx(more[k], rel=1e-6, abs=1e-9), k
    assert quiet["rmsDb"] == pytest.approx(more["rmsDb"] - 20.0, abs=1e-6)
    nof0 = ac.metrics(tone([(440, 0.5)]), SR, *f0_frames(None))
    assert nof0["pitch"] is None and nof0["pitchSpread"] is None and nof0["harmonicRatio"] is None and nof0["voicedDuration"] == 0.0
    assert nof0["centroid"] is not None
    silent = ac.metrics(np.zeros(int(0.6 * SR)), SR, *f0_frames(None))
    assert all(v is None for v in silent.values())


def test_envelope_times_and_bands():
    x = tone([(100, 0.5)], seconds=0.5, attack=0.05, release=0.3)
    m = ac.metrics(x, SR, *f0_frames(100, 0.5))
    assert m["attackTime"] == pytest.approx(40.0, abs=6)  # 10% → 90% 的线性起音 ≈ 0.8 × 50 ms
    assert m["decayTime"] == pytest.approx(0.8 * 300, abs=12)
    assert m["lowRatio"] > 0.95 and m["highRatio"] < 0.01
    noise = np.random.default_rng(0).normal(0, 0.1, int(0.5 * SR))
    n = ac.metrics(noise, SR, *f0_frames(None, 0.5))
    assert n["flatness"] > 0.5 > m["flatness"]
    assert n["highRatio"] > 0.5
    assert m["effectiveDuration"] == pytest.approx(0.5, abs=0.01)


def test_conditions():
    assert ac.check_conditions([{"metric": "pitch", "min": 60}, {"metric": "attackTime"}], "timbre") == [("pitch", 60.0, None)]
    from ottosmasher.core.errors import CoreError

    for bad in ([{"metric": "nope"}], [{"metric": "pitch", "min": 3, "max": 2}], "x"):
        with pytest.raises(CoreError):
            ac.check_conditions(bad, "timbre")


# ---------------------------------------------------------------- Core：准备、有效性、即时筛选


from test_rhythm_service import core, sample  # noqa: E402,F401 — 夹具：10 秒 200 Hz 正弦（3.4–4.25 秒静音）
from test_search_service import _put_f0  # noqa: E402


class _Ctx:
    def __init__(self, d):
        self.job_dir = d
        self.device = {}

    def progress(self, *a, **k):
        pass


def _prepare_and_adopt(c, tmp_path, scope=None):
    from ottosmasher.jobs import search as sj

    job = c.acoustic.prepare(scope or {})
    params = c.conn.execute("SELECT params FROM job WHERE id = ?", (job["id"],)).fetchone()[0]
    import json

    d = tmp_path / job["id"]
    d.mkdir()
    res = sj.acoustic(json.loads(params), _Ctx(d))
    c.acoustic.jobs.jobs_dir = tmp_path
    c.acoustic._adopt({"id": job["id"]}, res)
    return res


def test_prepare_filter_and_invalidation(core, tmp_path):
    a = sample(core, start=1.0, end=3.0, name="tone", nature="pitched")
    b = sample(core, start=3.45, end=4.2, name="silent", nature="unpitched")
    _put_f0(core, midi=55.0)  # 200 Hz ≈ MIDI 55.0
    st = core.acoustic.status({}, ["pitch", "attackTime"])
    assert (st["total"], st["ready"], st["stale"]) == (2, 0, 2) and st["missing"] == {"pitch": 2, "attackTime": 2}
    _prepare_and_adopt(core, tmp_path)
    st = core.acoustic.status({}, ["pitch", "effectiveDuration"])
    assert (st["ready"], st["stale"]) == (2, 0)
    assert st["missing"] == {"pitch": 1, "effectiveDuration": 1}  # 静音那条全部未知
    f = lambda conds: [r["name"] for r in core.samples.list(metrics={"mode": "timbre", "conditions": conds})["rows"]]  # noqa: E731
    assert f([{"metric": "pitch", "min": 54.5, "max": 55.5}]) == ["tone"]
    assert f([{"metric": "pitch", "min": 60}]) == []
    assert f([{"metric": "effectiveDuration", "min": 0.0}]) == ["tone"]  # 缺少指标的不命中
    assert sorted(f([])) == ["silent", "tone"]  # 没有条件 = 不筛
    # 采样范围变了 → 指标失效（内容变了），不再命中
    core.conn.execute("UPDATE sample SET \"end\" = 2.9 WHERE id = ?", (a,))
    assert f([{"metric": "pitch", "min": 54.5}]) == []
    assert core.acoustic.status({}, ["pitch"])["stale"] == 1
    with pytest.raises(Exception):
        core.samples.list(metrics={"mode": "timbre", "conditions": [{"metric": "bogus", "min": 1}]})
