"""原始能力（命令目录 ``layer = primitive``，所有者 2026-10-30）：只做计算、不改资料库。

像 git 的 plumbing：业务命令（语音分析、导入字幕……）建在同一套引擎上，这里把引擎直接开放给 agent 与脚本。
- 声音输入（``AudioRef``）二选一：库里的音轨（``assetId``，资产秒）或任意音频 / 视频文件（``path``，文件秒，``stream`` = 第几条音频流）。
- 对齐、读音分析、测音高是任务（模型 / 轻量通道，和语音分析共用模型与用户辞典）；逐条结果写在任务目录，用对应的 ``*Results`` 命令读。
- 读字幕文件是同步的：按当前字幕规则解释，不登记、不导入。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from ottosmasher.domain import oped_rule, subtitle_rules, subtitles
from ottosmasher.domain.mapping import check_range
from ottosmasher.media import probe as probe_mod
from ottosmasher.store.workspace import Workspace

from . import assets as assets_mod
from . import settings as settings_mod
from .edits import loads
from .errors import CoreError

KINDS = {"speech.align": "align", "text.analyze": "text", "f0.track": "f0"}


class PrimitiveService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, support_dir: Path, versions: Any) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.support_dir = support_dir
        self._versions = versions  # SpeechService._versions：模型与用户辞典的版本，和语音分析同一套

    # ------------------------------------------------------------ 声音输入

    def audio(self, ref: dict[str, Any]) -> dict[str, Any]:
        """AudioRef → 解码说明：文件、样本区间、窗口（输入时钟的秒）、资产映射（音轨输入才有）。"""
        has_asset, has_path = ref.get("assetId") is not None, ref.get("path") is not None
        if has_asset == has_path:
            raise CoreError("primitive-input-invalid", reason="asset-or-path")
        if has_asset:
            asset = assets_mod.get(self.conn, ref["assetId"])
            dur = float(asset["duration"])
            start, end = float(ref.get("start", 0.0)), float(ref.get("end", dur))
            start, end = check_range(start, end, dur, frame=1.0 / assets_mod.rate_of(self.conn, asset))
            sref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
            assets_mod.check_media(media)
            sr = sref.sample_rate
            a, b = round(win.to_file(start) * sr), round(win.to_file(end) * sr)
            return {"clock": "asset", "file": _file(sref), "frames": [a, b], "window": [win.to_local(a / sr), win.to_local(b / sr)],
                    "mapping": asset["mapping"] if isinstance(asset["mapping"], list) else loads(asset["mapping"])}
        path = str(Path(ref["path"]).expanduser())
        if not Path(path).is_file():
            raise CoreError("file-missing", path=path)
        pr = probe_mod.probe(path)
        n = int(ref.get("stream", 0))
        st = next((s for s in pr.audio if s.ordinal == n), None)
        if st is None or not st.sample_rate:
            raise CoreError("audio-stream-not-found", path=path, stream=n)
        dur = float(st.duration or pr.format_duration or 0.0)
        start, end = float(ref.get("start", 0.0)), float(ref.get("end", dur))
        start, end = check_range(start, end, dur, frame=1.0 / st.sample_rate)
        sr = int(st.sample_rate)
        a, b = round(start * sr), round(end * sr)
        f = {"path": path, "ordinal": st.ordinal, "sample_rate": sr, "channels": int(st.channels or 1), "codec": st.codec, "format": pr.format_name}
        return {"clock": "file", "file": f, "frames": [a, b], "window": [a / sr, b / sr], "mapping": None}

    def _model_params(self) -> dict[str, Any]:
        ver = self._versions()
        return {
            "dictionary": {"path": ver["dictionaryPath"], "version": ver["dictionary"]},
            "versions": {k: v for k, v in ver.items() if k != "dictionaryPath"},
            "models_dir": str(self.ws.models),
            "support_dir": str(self.support_dir),
        }

    def _submit(self, kind: str, items: list[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
        job = self.jobs.submit(kind, {"items": items, **extra})
        self.jobs.add_items(job["id"], [(str(i), "queued") for i in range(len(items))])
        return self.jobs.summary(job["id"])

    # ------------------------------------------------------------ 命令

    def align(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            raise CoreError("primitive-input-invalid", reason="no-items")
        out = []
        for i, it in enumerate(items):
            lines = it.get("lines")
            if lines is not None:
                if "text" in it or not isinstance(lines, list) or not lines or not all(isinstance(x, str) and x.strip() for x in lines):
                    raise CoreError("primitive-input-invalid", reason="lines", index=i)
                out.append({"idx": i, "text": "\n".join(lines), "lines": list(lines), **self.audio(it)})
                continue
            if not str(it.get("text", "")).strip():
                raise CoreError("primitive-input-invalid", reason="no-text", index=i)
            out.append({"idx": i, "text": it["text"], **self.audio(it)})
        return self._submit("speech.align", out, self._model_params())

    def analyze_text(self, texts: list[str]) -> dict[str, Any]:
        if not texts:
            raise CoreError("primitive-input-invalid", reason="no-items")
        return self._submit("text.analyze", [{"idx": i, "text": t} for i, t in enumerate(texts)], self._model_params())

    def f0(self, ref: dict[str, Any]) -> dict[str, Any]:
        a = self.audio(ref)
        return self._submit("f0.track", [{"idx": 0, **a}], {"models_dir": str(self.ws.models), "support_dir": str(self.support_dir)})

    def parse_subtitles(self, path: str, duration: float | None) -> dict[str, Any]:
        p = Path(path).expanduser()
        if not p.is_file():
            raise CoreError("file-missing", path=str(p))
        parsed = subtitles.read(p)
        values = settings_mod.values(self.conn)
        rules = subtitle_rules.SubtitleRules.build(values)
        cues, speakers = [], {}
        for cue in parsed.cues:
            c = subtitle_rules.classify(cue.text, rules)
            line = c.kind == "line"
            cues.append({"no": cue.order, "ref": cue.ref, "start": cue.start, "end": cue.end, "raw": cue.text, "kind": c.kind,
                         "text": c.align_text if line else c.name, "speakers": list(c.speakers) if line else [], "sfx": c.sfx, "withheld": c.withheld})
            for n in c.speakers if line else ():
                speakers[n] = speakers.get(n, 0) + 1
        dur = duration if duration is not None else max((c.end for c in parsed.cues), default=0.0)
        res = oped_rule.identify(parsed.cues, float(dur), values["subtitle.oped_start"], values["subtitle.oped_end"])
        return {
            "path": str(p), "format": parsed.format, "fingerprint": parsed.fingerprint, "cues": cues,
            "speakers": [{"name": k, "count": v} for k, v in sorted(speakers.items(), key=lambda kv: -kv[1])],
            "oped": {"pairs": [{"start": x.start, "end": x.end, "kind": x.suggest, "refs": [x.start_ref, x.end_ref]} for x in res.pairs], "errors": res.errors},
            "problems": parsed.problems,
        }

    # ------------------------------------------------------------ 结果

    def results(self, job_id: str, kind: str, offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        job = self.conn.execute("SELECT kind FROM job WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise CoreError("job-not-found", id=job_id)
        if job["kind"] != kind:
            raise CoreError("job-results-unavailable", id=job_id, kind=job["kind"])
        rows = self.conn.execute(
            "SELECT idx, status, error FROM job_item WHERE job_id=? ORDER BY idx LIMIT ? OFFSET ?", (job_id, int(limit), int(offset))
        ).fetchall()
        d = self.jobs.jobs_dir / job_id / "items"
        out = []
        for r in rows:
            row: dict[str, Any] = {"idx": r["idx"], "status": r["status"], "error": loads(r["error"]) if r["error"] else None}
            f = d / f"{r['idx']}.json"
            if r["status"] == "ok" and f.is_file():
                res = json.loads(f.read_text(encoding="utf-8"))
                if kind == "f0.track":
                    arr = np.load(d / f"{r['idx']}.npy").astype("<f4")
                    res |= {"f0": arr[:, 0].tobytes(), "confidence": arr[:, 1].tobytes(), "energy": arr[:, 2].tobytes()}
                row["result"] = res
            out.append(row)
        return out


def _file(ref: Any) -> dict[str, Any]:
    return {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": ref.sample_rate, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name}
