"""Versioned, interpretable sound descriptors; computation is never run by filtering."""

import json

import numpy as np

from .sample_scope import ids
from .workspace import identity

VERSION = "dsp-1"
# Definition, units and provenance are part of the contract, not arbitrary model JSON.
DEFINITIONS = {
    "sound.duration": ("有效声音时长", "s", "超过峰值 RMS 1% 的首尾范围"),
    "sound.attack": ("起音上升时间", "s", "有效区间开始至包络峰值前 10%→90%"),
    "sound.decay": ("尾部衰减时间", "s", "包络峰值后 90%→10%，未达到则未知"),
    "sound.crest": ("峰均比", "dB", "有效区间峰值相对 RMS"),
    "sound.rms": ("平均电平", "dBFS", "有效区间 RMS，无响度归一化"),
    "spectrum.low": ("低频占比", "ratio", "20–200 Hz 能量／20 Hz 以上总能量"),
    "spectrum.mid": ("中频占比", "ratio", "200–4000 Hz 能量占比"),
    "spectrum.high": ("高频占比", "ratio", "4000 Hz 以上能量占比"),
    "spectrum.centroid": ("频谱重心", "Hz", "幅度谱的频率均值"),
    "spectrum.flatness": ("噪声倾向", "ratio", "功率谱几何均值／算术均值"),
    "pitch.midi": ("原始音高", "MIDI", "可靠 F0 的半音中位数，A4=69"),
    "pitch.spread": ("音高波动", "semitone", "可靠 F0 的 90%–10% 分位范围"),
    "pitch.voiced_duration": ("可靠发声时长", "s", "仅可靠 F0 帧累计，不跨清音或缺失"),
    "harmonic.high": ("高阶谐波占比", "ratio", "第 5 阶以上谐波／全部匹配谐波能量"),
    "harmonic.ratio": ("谐波能量占比", "ratio", "可靠 F0 帧的谐波邻域能量／总能量"),
}


def ensure(db):
    schema = """
    CREATE TABLE IF NOT EXISTS feature_documents(material_id TEXT, producer TEXT, revision TEXT, payload TEXT, PRIMARY KEY(material_id,producer));
    CREATE TABLE IF NOT EXISTS feature_definitions(name TEXT, producer TEXT, payload TEXT, PRIMARY KEY(name,producer));
    CREATE TABLE IF NOT EXISTS feature_scalars(material_id TEXT, producer TEXT, name TEXT, value REAL, PRIMARY KEY(material_id,producer,name));
    CREATE INDEX IF NOT EXISTS feature_lookup ON feature_scalars(name,value);
    """
    for statement in schema.split(";"):
        if statement.strip():
            db.execute(statement)


def definitions():
    return [
        {
            "name": k,
            "title": v[0],
            "unit": v[1],
            "definition": v[2],
            "type": "number",
            "version": VERSION,
            "subject": "sample",
        }
        for k, v in DEFINITIONS.items()
    ]


def describe(samples, sr, frames=None):
    y = np.asarray(samples, dtype=float)
    if y.ndim == 1:
        y = y[:, None]
    values = dict.fromkeys(DEFINITIONS)
    if not len(y) or not np.isfinite(y).all():
        raise ValueError("空音频或非有限样本")
    hop = max(1, round(sr * 0.005))
    power = np.mean(y * y, axis=1)
    n = len(power) // hop
    env = np.sqrt(power[: n * hop].reshape(n, hop).mean(axis=1)) if n else np.array([np.sqrt(power.mean())])
    if env.max() < 1e-7:
        return {"values": values, "coverage": 0.0, "reason": "无可靠有效声音", "phases": {}}
    active = np.flatnonzero(env >= env.max() * 0.01)
    lo, hi = int(active[0] * hop), min(len(y), int((active[-1] + 1) * hop))
    clip = y[lo:hi]
    rms = np.sqrt(np.mean(clip**2))
    values.update(
        {
            "sound.duration": (hi - lo) / sr,
            "sound.rms": float(20 * np.log10(max(rms, 1e-12))),
            "sound.crest": float(20 * np.log10(max(np.max(np.abs(clip)), 1e-12) / max(rms, 1e-12))),
        }
    )
    peak = int(np.argmax(env))
    pre = env[active[0] : peak + 1]
    ten = np.flatnonzero(pre >= env.max() * 0.1)
    ninety = np.flatnonzero(pre >= env.max() * 0.9)
    values["sound.attack"] = float((ninety[0] - ten[0]) * hop / sr) if len(ten) and len(ninety) else None
    after = env[peak:]
    d90, d10 = np.flatnonzero(after <= env.max() * 0.9), np.flatnonzero(after <= env.max() * 0.1)
    values["sound.decay"] = float((d10[0] - d90[0]) * hop / sr) if len(d90) and len(d10) else None
    size = min(8192, max(128, int(sr * 0.04)))
    hop_fft = max(1, size // 4)
    if len(clip) < size:
        spectra = np.abs(np.fft.rfft(clip * np.hanning(len(clip))[:, None], n=size, axis=0)) ** 2
        spectra = spectra.mean(axis=1)[None, :]
        times = np.array([(lo + len(clip) / 2) / sr])
    else:
        windows = np.lib.stride_tricks.sliding_window_view(clip, size, axis=0)[::hop_fft]
        spectra = (np.abs(np.fft.rfft(windows * np.hanning(size), axis=-1)) ** 2).mean(axis=1)
        times = (lo + np.arange(len(spectra)) * hop_fft + size / 2) / sr
    freq = np.fft.rfftfreq(size, 1 / sr)

    def spectral(sp):
        p = sp.mean(axis=0)
        valid = freq >= 20
        total = max(float(p[valid].sum()), 1e-30)
        mag = np.sqrt(p)
        return {
            "spectrum.low": float(p[(freq >= 20) & (freq < 200)].sum() / total),
            "spectrum.mid": float(p[(freq >= 200) & (freq < 4000)].sum() / total),
            "spectrum.high": float(p[freq >= 4000].sum() / total),
            "spectrum.centroid": float(np.sum(freq * mag) / max(mag.sum(), 1e-30)),
            "spectrum.flatness": float(
                np.exp(np.mean(np.log(p[valid] + 1e-30))) / max(np.mean(p[valid]), 1e-30)
            ),
        }

    values.update(spectral(spectra))
    phases = {}
    for name, a, b in (
        ("attack", lo / sr, min(hi / sr, lo / sr + 0.05)),
        ("body", lo / sr + (hi - lo) / sr / 3, lo / sr + (hi - lo) / sr * 2 / 3),
        ("tail", lo / sr + (hi - lo) / sr * 2 / 3, hi / sr),
    ):
        mask = (times >= a) & (times < b)
        phases[name] = spectral(spectra[mask]) if np.any(mask) else None
    coverage = 0.0
    if frames and len(frames.get("times", [])):
        t, f0, conf, voiced = [np.asarray(frames[k]) for k in ("times", "f0_hz", "confidence", "voiced")]
        good = (t >= lo / sr) & (t < hi / sr) & (f0 > 0) & (conf >= 0.5) & voiced.astype(bool)
        step = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
        coverage = float(np.sum(good) / max(1, np.sum((t >= lo / sr) & (t < hi / sr))))
        if good.sum() >= 3:
            midi = 69 + 12 * np.log2(f0[good] / 440)
            values.update(
                {
                    "pitch.midi": float(np.median(midi)),
                    "pitch.spread": float(np.quantile(midi, 0.9) - np.quantile(midi, 0.1)),
                    "pitch.voiced_duration": float(np.sum(good) * step),
                }
            )
            ratios, highs = [], []
            for ts, sp in zip(times, spectra):
                i = int(np.argmin(abs(t - ts)))
                if (
                    not good[i]
                    or abs(t[i] - ts) > max(0.02, step * 1.5)
                    or f0[i] < 3 * sr / size
                    or len(clip) / sr < 3 / f0[i]
                ):
                    continue
                centers = np.arange(1, int((sr / 2) / f0[i]) + 1) * f0[i]
                width = min(f0[i] * 0.2, max(sr / size * 1.2, f0[i] * 0.04))
                bins = abs(freq[:, None] - centers[None, :]) <= width
                all_energy = float(sp[bins.any(axis=1)].sum())
                ratios.append(all_energy / max(float(sp.sum()), 1e-30))
                highs.append(float(sp[bins[:, 4:].any(axis=1)].sum()) / max(all_energy, 1e-30))
            if ratios:
                values["harmonic.ratio"], values["harmonic.high"] = (
                    float(np.mean(ratios)),
                    float(np.mean(highs)),
                )
    return {
        "values": values,
        "phases": phases,
        "coverage": coverage,
        "effective_range": [lo / sr, hi / sr],
        "reason": None if coverage else "可靠 F0 不足；频谱与瞬态仍可用",
    }


def store(db, mid, producer, revision, document, defs, commit=True):
    ensure(db)
    by_name = {d["name"]: d for d in defs}
    for name, val in document["values"].items():
        if name not in by_name or (
            val is not None and (not isinstance(val, (int, float)) or not np.isfinite(val))
        ):
            raise ValueError("特征必须具有定义及有限数值或 null")
    for d in defs:
        if (
            not all(k in d for k in ("name", "unit", "definition", "version", "subject", "type"))
            or d["type"] != "number"
        ):
            raise ValueError("特征定义缺少类型、单位、版本或作用对象")
        db.execute(
            "INSERT OR REPLACE INTO feature_definitions VALUES(?,?,?)", (d["name"], producer, json.dumps(d))
        )
    db.execute("DELETE FROM feature_scalars WHERE material_id=? AND producer=?", (mid, producer))
    db.executemany(
        "INSERT INTO feature_scalars VALUES(?,?,?,?)",
        [(mid, producer, k, v) for k, v in document["values"].items()],
    )
    db.execute(
        "INSERT OR REPLACE INTO feature_documents VALUES(?,?,?,?)",
        (mid, producer, revision, json.dumps(document)),
    )
    if commit:
        db.commit()


def analyze(db, scope):
    import soundfile as sf

    from . import sample_analysis, sample_audio

    ensure(db)
    done, errors = [], []
    for mid in ids(db, scope):
        try:
            asset = sample_audio.resolve(db, mid)
            try:
                r = sample_analysis.ready(db, mid)
            except ValueError:
                r = None
            rev = identity(VERSION, asset, r["signature"] if r else None)
            previous = db.execute(
                "SELECT revision FROM feature_documents WHERE material_id=? AND producer=?", (mid, "otto.dsp")
            ).fetchone()
            if not previous or previous[0] != rev:
                y, sr = sf.read(sample_audio.pcm(asset), always_2d=True)
                document = {
                    **describe(y, sr, r.get("frames") if r else None),
                    "audio_identity": identity(asset),
                    "analysis_revision": r["signature"] if r else None,
                    "producer": "otto.dsp",
                    "version": VERSION,
                    "sample_rate": sr,
                }
                store(db, mid, "otto.dsp", rev, document, definitions())
            done.append(mid)
            print(f"声学特征 {len(done)}: {mid}", flush=True)
        except (ValueError, OSError) as e:
            errors.append({"material_id": mid, "error": str(e)})
    return {"type": "features", "completed": len(done), "errors": errors}


def read(db, mid, producer="otto.dsp"):
    from . import sample_audio

    ensure(db)
    row = db.execute(
        "SELECT payload FROM feature_documents WHERE material_id=? AND producer=?", (mid, producer)
    ).fetchone()
    if not row:
        return None
    d = json.loads(row[0])
    if d.get("audio_identity") != identity(sample_audio.resolve(db, mid)):
        return None
    if d.get("analysis_revision"):
        r = db.execute(
            "SELECT r.signature FROM sample_records r JOIN materials m ON m.id=r.material_id AND m.active_phone_backend=r.backend WHERE m.id=?",
            (mid,),
        ).fetchone()
        if not r or r[0] != d["analysis_revision"]:
            return None
    return d


def filter_ids(db, candidates, conditions, producer="otto.dsp"):
    unknown, found = 0, []
    for mid in candidates:
        docs = {}
        for owner in {c.get("producer", producer) for c in conditions}:
            try:
                docs[owner] = read(db, mid, owner)
            except (ValueError, OSError):
                docs[owner] = None
        values = [
            ((docs[c.get("producer", producer)] or {}).get("values") or {}).get(c["name"]) for c in conditions
        ]
        if any(v is None for v in values):
            unknown += 1
            continue
        if all(
            (c.get("min") is None or v >= float(c["min"])) and (c.get("max") is None or v <= float(c["max"]))
            for c, v in zip(conditions, values)
        ):
            found.append(mid)
    return found, unknown
