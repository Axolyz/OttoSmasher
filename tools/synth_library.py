"""合成检索库（ARCHITECTURE §9.5）：约 3 万条 × 3 秒的语音采样，写进独立的临时工作区（默认 ``.cache/perf/ws``，不碰用户工作区）。

用法：``.venv/bin/python tools/synth_library.py [--samples 30000] [--out .cache/perf/ws] [--seed 7]``

每 300 条采样共用一个 15 分钟的资产（共 100 个“原片”），采样首尾相接、各 3 秒。每条采样：
- 合成对齐（约 8–12 个“辅音 + 元音”音节，偶尔一个停顿），写成采样自己的语音测量头；
- 合成 F0（每个音节一个音高，MIDI 52–76，带一点抖动；音节之间无声）与能量，按资产写进 F0 测量（与真实测量同一布局与身份）；
- 语音检索索引：用与真实构建相同的纯函数（音块、停顿段、语段、量化、逐块属性、持续终点）直接建好，按真实的失效键写入。
没有真实音频文件（检索不读波形）：资产的存储指向一个不存在的路径，只用于身份计算。固定随机种子，结果可复现。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from ottosmasher.algo import rhythm as rh  # noqa: E402
from ottosmasher.algo import speech_search as ss  # noqa: E402
from ottosmasher.core.clock import new_id, now_iso  # noqa: E402
from ottosmasher.core.edits import dumps  # noqa: E402
from ottosmasher.models import f0store, fcpe  # noqa: E402
from ottosmasher.store.db import connect, migrate, transaction  # noqa: E402
from ottosmasher.store.workspace import Workspace  # noqa: E402

PER_ASSET = 300
SAMPLE_SECONDS = 3.0
SR = 48000
CONSONANTS = ["k", "s", "t", "n", "h", "m", "r", "sh", "ch", "g", "d", "b"]
VOWELS = ["a", "i", "u", "e", "o"]
CHARACTERS = [None, "character:京子", "character:結衣", "character:ちなつ", "character:あかり"]


def synth_sample(rng: np.random.Generator, t0: float) -> tuple[list[dict], np.ndarray, list[tuple[float, float]]]:
    """一条 3 秒采样：音素（资产局部秒）、逐帧 [F0, 置信度, 能量]（300 帧）、停顿。"""
    frames = np.zeros((300, 3), dtype=np.float32)
    frames[:, 1] = 0.02
    frames[:, 2] = 1e-9
    phones: list[dict] = []
    t = 0.05
    pauses = []
    mora = 0
    base = rng.uniform(56, 70)
    while t < SAMPLE_SECONDS - 0.25:
        if rng.random() < 0.06 and t > 0.5:
            gap = rng.uniform(0.3, 0.5)
            phones.append({"label": "pau", "start": round(t0 + t, 4), "end": round(t0 + t + gap, 4), "mora": None})
            pauses.append((t, t + gap))
            t += gap
            continue
        c = CONSONANTS[rng.integers(len(CONSONANTS))]
        v = VOWELS[rng.integers(len(VOWELS))]
        cd = rng.uniform(0.03, 0.06)
        vd = rng.uniform(0.12, 0.28)
        phones.append({"label": c, "start": round(t0 + t, 4), "end": round(t0 + t + cd, 4), "mora": mora})
        a, b = t + cd, t + cd + vd
        phones.append({"label": v, "start": round(t0 + a, 4), "end": round(t0 + b, 4), "mora": mora, "strength": float(rng.uniform(0.2, 1.0))})
        midi = base + rng.normal(0, 3)
        i0, i1 = int(a / 0.01), min(300, int(b / 0.01))
        frames[i0:i1, 0] = 440.0 * 2 ** ((midi + rng.normal(0, 0.08, i1 - i0) - 69) / 12)
        frames[i0:i1, 1] = np.where(rng.random(i1 - i0) < 0.05, 0.3, 0.92)
        frames[i0:i1, 2] = rng.uniform(1e-3, 1e-2)
        mora += 1
        t = b + rng.uniform(0.0, 0.03)
    return phones, frames, pauses


def build_row(args: tuple) -> tuple[str, bytes | None]:
    import msgspec

    sid, phones_d, frames, t0, char, penalty = args
    phones = [rh.Phone(p["label"], p["start"], p["end"], p.get("mora"), p.get("strength")) for p in phones_d]
    window = (t0, t0 + SAMPLE_SECONDS)
    try:
        blocks = rh.group_blocks(phones)
    except Exception:  # noqa: BLE001
        return sid, None
    if not blocks:
        return sid, None
    # 停顿：用与规格相同的能量门限思路在合成 RMS 上检测会依赖音频；合成库直接用标注的停顿（内缩 20 ms）
    pauses = [rh.Pause(round(p["start"] + rh.PAUSE_INSET, 6), round(p["end"] - rh.PAUSE_INSET, 6)) for p in phones_d if p["label"] == "pau"]
    pseg = rh.pause_segments(blocks, pauses)
    cuts = rh.find_cuts(blocks, pauses, phones)
    segs = rh.segments(blocks, cuts, window)
    dur = rh.durations(blocks, pauses, window)
    raw = rh.quantize_raw(dur, pseg, {}, penalty)
    times = window[0] + (np.arange(300) * fcpe.HOP + fcpe.HOP / 2) / fcpe.SR
    fr = frames.astype(np.float64)
    have = np.ones(300, dtype=bool)
    attrs = rh.block_attributes(blocks, phones, pseg, times, fr, have)
    thr = ss.active_threshold(fr[:, 2], have)
    sustain = [ss.sustain_end(b, pauses, times, fr[:, 2], have, thr, False) for b in blocks]
    idx = ss.build_index(sid, phones, blocks, pauses, pseg, cuts, segs, dur, list(raw.cells or []), window, SR, attrs, sustain,
                         [char] * len(blocks), {}, penalty)
    return sid, msgspec.msgpack.encode(ss.to_wire(idx, [b.members for b in blocks]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=30000)
    ap.add_argument("--out", default=str(ROOT / ".cache" / "perf" / "ws"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if not str(out).startswith(str(ROOT / ".cache")):
        sys.exit("refusing to write outside the repository's .cache/")
    if out.exists():
        shutil.rmtree(out)
    ws = Workspace(out)
    ws.ensure()
    conn = connect(ws.db_path)
    migrate(conn, ws.backups)
    rng = np.random.default_rng(args.seed)
    t_start = time.time()
    n_assets = math.ceil(args.samples / PER_ASSET)
    asset_dur = PER_ASSET * SAMPLE_SECONDS
    ts = now_iso()
    jobs = []
    f0_sha = None
    from ottosmasher.core.search_index import asset_identities, f0_sha as sha_of, speech_keys

    f0_sha = sha_of()
    with transaction(conn):
        for k in range(n_assets):
            src, aid, mid = new_id(), new_id(), new_id()
            snap = {"size": 1000 + k, "mtime_ns": 1700000000000000000 + k}
            conn.execute(
                "INSERT INTO source(id, path, work, episode, source_type, duration, file_snapshot, created_at, updated_at) VALUES (?, ?, ?, ?, '动画', ?, ?, ?, ?)",
                (src, f"/synthetic/ep{k:03d}.mkv", "Synth", f"{k:03d}", asset_dur, dumps(snap), ts, ts),
            )
            conn.execute("INSERT INTO source_stream(source_id, kind, ordinal, container_index, codec, sample_rate, channels) VALUES (?, 'audio', 1, 1, 'flac', ?, 2)", (src, SR))
            conn.execute("INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, created_at) VALUES (?, ?, 'external', ?, 'matroska', ?, ?)",
                         (mid, f"/synthetic/ep{k:03d}.mkv", dumps(snap), SR, ts))
            conn.execute(
                "INSERT INTO sound_asset(id, source_id, origin, media_file_id, stream_ordinal, duration, mapping, created_at) VALUES (?, ?, 'stream', ?, 1, ?, ?, ?)",
                (aid, src, mid, asset_dur, json.dumps([[0, 0], [asset_dur, asset_dur]]), ts),
            )
            conn.execute("INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, ?, ?, 'primary')", (aid, asset_dur, mid))
            n_here = min(PER_ASSET, args.samples - k * PER_ASSET)
            all_frames = np.zeros((f0store.total_frames(asset_dur), 3), dtype=np.float32)
            all_frames[:, 1] = 0.02
            all_frames[:, 2] = 1e-9
            for j in range(n_here):
                sid = new_id()
                t0 = j * SAMPLE_SECONDS
                phones, frames, _ = synth_sample(rng, t0)
                char = CHARACTERS[rng.integers(len(CHARACTERS))]
                conn.execute(
                    'INSERT INTO sample(id, asset_id, start, "end", name, nature, created_via, created_at, updated_at) VALUES (?, ?, ?, ?, ?, \'speech\', \'manual\', ?, ?)',
                    (sid, aid, t0, t0 + SAMPLE_SECONDS, f"合成 {k:03d}-{j:03d}", ts, ts),
                )
                if char:
                    conn.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, ?)", (sid, char))
                # 分析属于“文本层的段 + 资产”（所有者 2026-10-09）：每个采样一段（与采样同区间），采样按判定区间（= 选区）读到它
                rid, seg = new_id(), new_id()
                conn.execute(
                    'INSERT INTO text_segment(id, source_id, start, "end", text, origin, created_at, updated_at) VALUES (?, ?, ?, ?, \'あ\', \'subtitle\', ?, ?)',
                    (seg, src, t0, t0 + SAMPLE_SECONDS, ts, ts),
                )
                sp = [p for p in phones if p["label"] != "pau"]
                conn.execute(
                    "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at,"
                    " span_start, span_end, seg_start, seg_end, seg_text) VALUES (?, 'alignment', 'asset_text', ?, ?, ?, ?, ?, 'ok', 0, ?, ?, ?, ?, ?, ?, 'あ')",
                    (rid, f"seg:{seg}@{aid}", aid, t0, t0 + SAMPLE_SECONDS, dumps({"audio": {"snapshot": snap}, "text": "あ"}),
                     dumps({"phones": phones, "morae": []}), ts, sp[0]["start"] if sp else None, sp[-1]["end"] if sp else None, t0, t0 + SAMPLE_SECONDS),
                )
                conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('asset_text', ?, 'alignment', ?, 1)", (f"seg:{seg}@{aid}", rid))
                i0 = int(round(t0 / 0.01))
                all_frames[i0 : i0 + 300] = frames
                jobs.append((sid, phones, frames, t0, char, 1.0))
            ident = asset_identities(conn, {aid: [(0.0, asset_dur)]}, f0_sha)[aid]["identities"][(0.0, asset_dur)]
            tmp = out / "chunk.npy"
            for c in range(math.ceil(len(all_frames) / f0store.CHUNK_FRAMES)):
                np.save(tmp, all_frames[c * f0store.CHUNK_FRAMES : (c + 1) * f0store.CHUNK_FRAMES])
                f0store.adopt_chunk(ws.f0, aid, ident, c, tmp, {"model": f0_sha, "frontend": fcpe.FRONTEND_VERSION})
            tmp.unlink(missing_ok=True)
            rf = new_id()
            conn.execute(
                "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, inputs, status, manual, result, created_at) VALUES (?, 'f0', 'asset', ?, ?, '{}', 'ok', 0, '{}', ?)",
                (rf, aid, aid, ts),
            )
            conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('asset', ?, 'f0', ?, 1)", (aid, rf))
    t_db = time.time()
    print(f"database + F0: {len(jobs)} samples on {n_assets} assets in {t_db - t_start:.1f} s", flush=True)
    keys = speech_keys(conn, [j[0] for j in jobs])
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for sid, data in pool.map(build_row, jobs, chunksize=64):
            rows.append((sid, keys[sid][0], "ok" if data else "none", None if data else "rhythm-no-blocks", data, ts))
    with transaction(conn):
        conn.executemany("INSERT INTO speech_index(sample_id, input_key, status, reason, data, built_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(f"speech index: {sum(1 for r in rows if r[2] == 'ok')} rows in {time.time() - t_db:.1f} s; workspace {out}", flush=True)


if __name__ == "__main__":
    main()
