"""Subtitle review ledger; run with otto run. This helper never changes library objects.

scan parsed.json task.json --input backup_source.srt --precision fine --goal "..."
     [--audio-export wav-export.json] [--extra-cases cases.json]
packet task.json cue:12 --asset-id ID --directory /task/evidence
check task.json

parsed.json is the unmodified subtitles.parse result. An optional audio-export
is exports.wav JSON (path and mapping), not guessed offsets. Evidence contains
file paths and a short explanation. Edit decisions in task.json after inspection:
status = kept | changed | uncertain; reason = judgement; evidence = [{path, note}].
Prepared packets do not mark any item reviewed. Screening flags are heuristic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def fingerprint(path):
    p = Path(path).resolve()
    with p.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(p), "sha256": digest}


def save(path, value):
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def scan(parsed, inputs, precision, goal, energy=None, extra=()):
    cues = sorted((c for c in parsed["cues"] if c["kind"] == "line"), key=lambda c: (c["start"], c["end"], c["no"]))
    items = {}
    patterns = {}
    previous = None
    for cue in cues:
        lines = [ln.strip() for ln in cue["raw"].splitlines() if ln.strip()]
        pattern = ["bracket-only" if re.fullmatch(r"[\uFF08(].*[\uFF09)]", ln) else
                   "labelled" if re.match(r"^[-\uFF0D\u2014]?\s*[\uFF08(]", ln) else "unlabelled" for ln in lines]
        key = " / ".join(pattern)
        patterns[key] = patterns.get(key, 0) + 1
        flags = []
        if len(lines) > 1:
            flags.append("multiline: inspect actual turn convention")
        if cue.get("withheld") or len(cue.get("speakers", [])) > 1:
            flags.append("speaker ambiguity or multiple people")
        if previous and cue["start"] < previous["end"]:
            flags.append("overlap: establish simultaneous speech or bad boundary")
            items[f'cue:{previous["no"]}']["flags"].append("overlap with next cue")
        if cue["end"] - cue["start"] < .2:
            flags.append("short cue: check contents and turn")
        if energy:
            flags.extend(energy(cue))
        items[f'cue:{cue["no"]}'] = {"id": f'cue:{cue["no"]}', "start": cue["start"], "end": cue["end"],
                                  "text": cue["text"], "raw": cue["raw"], "flags": flags,
                                  "status": "pending", "reason": "", "evidence": []}
        if previous is None or cue["end"] > previous["end"]:
            previous = cue
    selected = [v for v in items.values() if v["flags"]]
    by_id = {v["id"]: v for v in selected}
    for case in extra:
        if case["id"] in by_id:
            by_id[case["id"]]["flags"].extend(case["flags"])
        else:
            by_id[case["id"]] = {**case, "status": "pending", "reason": "", "evidence": []}
    return {"version": 1, "goal": goal, "precision": precision, "inputs": [fingerprint(p) for p in inputs],
            "lineCount": len(cues), "patterns": patterns, "screening": "heuristic; no boundaries changed",
            "items": list(by_id.values())}


def energy_screen(export):
    import numpy as np
    from ottosmasher.domain.mapping import Mapping

    mapping = Mapping.of(export["mapping"])
    pcm = np.frombuffer(subprocess.check_output(["ffmpeg", "-v", "error", "-i", export["path"],
                                               "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]), dtype="<f4")
    block = 160  # 10 ms energy, used only to flag, never to move a boundary.
    pcm = pcm[:len(pcm) // block * block]
    if len(pcm) == 0:
        raise ValueError("empty audio")
    rms = np.sqrt(np.mean(pcm.reshape(-1, block) ** 2, axis=1))
    threshold = max(1e-6, float(np.quantile(rms, .75)) * .1)

    def check(cue):
        flags = []
        for label, t in (("start", cue["start"]), ("end", cue["end"])):
            try:
                local = mapping.to_local(t)
            except Exception as exc:
                raise ValueError(f"audio export does not cover cue {cue['no']} {label}") from exc
            i = round(local * 100)
            if i < 4 or i + 4 >= len(rms):
                flags.append(f"{label}: insufficient audio context")
                continue
            if np.max(rms[i-4:i]) >= threshold and np.max(rms[i:i+4]) >= threshold:
                flags.append(f"{label}: energy on both sides, even without a silence gap")
        return flags
    return check


def check(report, base):
    errors = []
    for record in report["inputs"]:
        p = Path(record["path"])
        if not p.is_file() or fingerprint(p)["sha256"] != record["sha256"]:
            errors.append(f"input changed or missing: {p}")
    counts = {key: 0 for key in ("pending", "kept", "changed", "uncertain")}
    seen = set()
    for item in report["items"]:
        if item["id"] in seen:
            errors.append(f"duplicate item: {item['id']}")
        seen.add(item["id"])
        status = item["status"]
        if status not in counts:
            errors.append(f"unknown status: {item['id']}")
            continue
        counts[status] += 1
        if status == "pending":
            continue
        if not item.get("reason") or not item.get("evidence"):
            errors.append(f"missing reason or evidence: {item['id']}")
        for evidence in item.get("evidence", []):
            p = Path(evidence["path"])
            if not p.is_absolute():
                p = base / p
            if not p.is_file() or not evidence.get("note"):
                errors.append(f"missing evidence file or note: {item['id']}")
    if report["precision"] == "fine" and counts["pending"]:
        errors.append("fine review still has pending items")
    return {"ok": not errors, "counts": counts, "errors": errors,
            "contentQuality": "not automatically verified"}


def packet(report, item_id, asset_id, directory):
    from ottosmasher.cli.client import LinkClient
    from ottosmasher.domain.mapping import Mapping

    item, = [v for v in report["items"] if v["id"] == item_id]
    with LinkClient.from_env() as client:
        asset = client.call("assets.get", {"id": asset_id})
        mapping = Mapping.of(asset["mapping"])
        a = mapping.to_source(0)
        b = mapping.to_source(asset["duration"])
        if item["start"] < a or item["end"] > b:
            raise ValueError("asset does not cover the complete cue; choose a fuller track")
        start = mapping.to_local(max(a, item["start"] - 1.0))
        end = mapping.to_local(min(b, item["end"] + 1.0))
        result = client.call("exports.wav", {"assetId": asset_id, "start": start, "end": end,
                                            "content": item_id.replace(":", "-"), "track": "review", "directory": str(directory)})
    return {"item": item_id, "cue": [item["start"], item["end"]], "audio": result,
            "reviewed": False, "next": "inspect full waveform and sentence contents; record judgement in ledger"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("scan")
    p.add_argument("parsed"); p.add_argument("task")
    p.add_argument("--input", action="append", required=True)
    p.add_argument("--precision", choices=("quick", "standard", "fine"), required=True)
    p.add_argument("--goal", required=True)
    p.add_argument("--audio-export"); p.add_argument("--extra-cases")
    p = commands.add_parser("check"); p.add_argument("task")
    p = commands.add_parser("packet"); p.add_argument("task"); p.add_argument("id")
    p.add_argument("--asset-id", required=True); p.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "scan":
        if Path(args.task).exists():
            parser.error("task exists; preserve decisions and create a new revision instead")
        files = [args.parsed, *args.input]
        energy = None
        if args.audio_export:
            export = load(args.audio_export)
            files.extend([args.audio_export, export["path"]])
            energy = energy_screen(export)
        extra = load(args.extra_cases) if args.extra_cases else []
        if args.extra_cases:
            files.append(args.extra_cases)
        report = scan(load(args.parsed), files, args.precision, args.goal, energy, extra)
        save(args.task, report)
        print(json.dumps({"lines": report["lineCount"], "patterns": report["patterns"], "candidates": len(report["items"])}))
    elif args.command == "check":
        result = check(load(args.task), Path(args.task).resolve().parent)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    else:
        directory = args.directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        result = packet(load(args.task), args.id, args.asset_id, directory)
        save(directory / (args.id.replace(":", "-") + ".json"), result)
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
