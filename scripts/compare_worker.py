from ottosmasher.inference_runtime import onnx_session

"""Isolated ONNX model worker. Raw context output is never overwritten by import."""

import argparse
import hashlib
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

import pyopenjtalk

from ottosmasher.workspace import CODE_ROOT, ROOT

sys.path.insert(0, str(CODE_ROOT / "src"))
from ottosmasher.ctc import forced_ctc


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    tmp.replace(path)


def reading(text):
    from ottosmasher.g2p_frontend import generate

    result = generate(text)
    return (
        result["mora"],
        result["phones"],
        [idx for phone, idx in zip(result["phones"], result["phone_mora"]) if phone not in {"pau", "sil"}],
    )


def transcript(item, kind):
    owners, seq, raw_records, moras = [], [], [], {}
    for c in item["context"]:
        frontend = item.get("frontends", {}).get(c["id"])
        if frontend:
            mora, raw = frontend["mora"], frontend["phones"]
            indices = [idx for phone, idx in zip(raw, frontend["phone_mora"]) if phone not in {"pau", "sil"}]
        else:
            mora, raw, indices = reading(c.get("alignment_text", c["spoken"]))
        moras[c["id"]] = mora
        raw_records.append({"cue_id": c["id"], "phones": raw, "frontend": frontend})
        j = 0
        for p in raw:
            idx = indices[j] if p not in {"pau", "sil"} else None
            j += p not in {"pau", "sil"}
            mapped = p.lower() if p in {"I", "U"} else p
            if mapped in {"pau", "sil", "cl"} and kind == "phonetic":
                mapped = "SP"
            if mapped == "sil":
                mapped = "pau"
            seq.append(mapped)
            if mapped not in {"SP", "pau"}:
                owners.append(
                    {"phone": mapped, "cue_id": c["id"], "mora_index": idx, "reading": mora["reading"]}
                )
        seq.append("SP" if kind == "phonetic" else "pau")
    return seq, owners, raw_records, moras


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("kind", choices=["phonetic", "pydomino", "narabas"])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--exclude-cues", default="")
    args = parser.parse_args()
    init_started = time.monotonic()
    kind = args.kind
    if kind == "phonetic":
        sys.path.insert(0, str(CODE_ROOT / "vendor/HubertFA"))
        sys.path.insert(0, str(CODE_ROOT / "scripts"))
        from hubert_worker import RuntimeInference
        from praatio import textgrid

        model = ROOT / "models/hubert/1218_hfa_model_new_dict/model.onnx"
        engine = RuntimeInference(model)
        engine.load_config()
        engine.init_decoder()
        engine.load_model()
    elif kind == "pydomino":
        from ottosmasher import domino_adapter as pydomino
        from ottosmasher.model_inventory import model_path
        import soundfile as sf

        model = model_path("models/pydomino/phoneme_transition_model.onnx")
        engine = pydomino.Aligner(str(model))
    else:
        import onnxruntime as ort
        import soundfile as sf

        sys.path.insert(0, str(CODE_ROOT / "vendor/narabas"))
        # Import the data-only symbol table without executing narabas.__init__ (imports torch).
        import runpy

        symbols = runpy.run_path(str(CODE_ROOT / "vendor/narabas/narabas/symbols.py"))
        BOS, EOS, phoneme_to_id = symbols["BOS"], symbols["EOS"], symbols["phoneme_to_id"]

        model = ROOT / "models/narabas/narabas-v0.onnx"
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        engine = onnx_session(model, options)
        meta = engine.get_modelmeta().custom_metadata_map
        rate, hop = int(meta["sample_rate"]), int(meta["hop_length"])
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    print(f"Stage {kind} initialization: {time.monotonic() - init_started:.3f}s", flush=True)
    manifest = json.loads((args.folder / "manifest.json").read_text())
    for i, spec in enumerate(manifest["cues"][: args.limit]):
        if spec["id"] in args.exclude_cues.split(","):
            print("Skipped confirmed OP/ED: " + spec["id"], flush=True)
            continue
        output = args.folder / kind / spec["id"] / "result.json"
        if output.exists() and not args.retry:
            continue
        input_path = args.folder / "inputs" / (spec["id"] + ".json")
        begun = time.time()
        result = {
            "backend": kind,
            "model_sha256": digest,
            "input": str(input_path),
        }
        try:
            item = json.loads(input_path.read_text())
            result["input_audio_sha256"] = item["audio_lineage"]["audio_sha256"]
            seq, owners, raw, moras = transcript(item, kind)
            result.update(g2p=raw, phone_owners=owners, mora=moras)
            output.parent.mkdir(parents=True, exist_ok=True)
            import contextlib
            from ottosmasher.audio_storage import model_input, read, lineage_audio

            sample_rate = 44100 if kind == "phonetic" else 16000
            in_memory = bool(item.get("input_audio") and kind != "phonetic")
            if in_memory:
                audio, sr = read(
                    *lineage_audio(item["input_audio"]),
                    rate=sample_rate,
                    channels=1,
                    stream=item["input_audio"].get("file_audio_stream", 0),
                )
                y = audio[:, 0]
                input_context = contextlib.nullcontext(None)
            else:
                input_context = (
                    model_input(item["input_audio"], sample_rate)
                    if item.get("input_audio")
                    else contextlib.nullcontext(item[f"wav_{sample_rate}"])
                )
            with input_context as prepared:
                result["converted_audio_sha256"] = hashlib.sha256(
                    y.tobytes() if in_memory else Path(prepared).read_bytes()
                ).hexdigest()
                if kind == "phonetic":
                    from ottosmasher.hubert_pauses import align

                    result["phones"] = align(engine, str(prepared), seq)
                    result["decoder"] = "hubert-explicit-pauses-v1"
                    result["closure_not_separately_aligned"] = any("cl" in x["phones"] for x in raw)
                elif kind == "pydomino":
                    if not in_memory:
                        y, sr = sf.read(str(prepared), dtype="float32")
                    if sr != 16000 or y.ndim != 1:
                        raise ValueError("pydomino requires 16 kHz mono vocals")
                    sequence = ["pau"] + seq
                    sequence = [
                        p for j, p in enumerate(sequence) if not (p == "pau" and j and sequence[j - 1] == p)
                    ]
                    # 10 ms minimum preserves real very short phones (upstream example uses 30 ms).
                    spans = engine.align(y, " ".join(sequence), 1)
                    result.update(
                        min_frame=1,
                        phones=[{"start": float(a), "end": float(b), "label": p} for a, b, p in spans],
                    )
                else:
                    if not in_memory:
                        y, sr = sf.read(str(prepared), dtype="float32")
                    if sr != rate:
                        raise ValueError(f"narabas requires {rate} Hz")
                    logits = engine.run(None, {"input": y[None, :]})[0]

                    ids = [BOS] + [phoneme_to_id[p] for p in seq] + [EOS]
                    spans = forced_ctc(logits[0], ids)
                    result["decoder"] = "ottosmasher-ctc-viterbi-v1"
                    result["phones"] = [
                        {"start": a * hop / rate, "end": b * hop / rate, "label": p}
                        for p, (a, b) in zip(seq, spans[1:-1])
                    ]
        except Exception as exc:  # noqa: BLE001 - isolate and retain each backend failure
            import traceback

            result.update(error=str(exc), traceback=traceback.format_exc())
        result["runtime_seconds"] = time.time() - begun
        save(output, result)
        print(
            f"{kind} {i + 1}/{len(manifest['cues'])} {spec['id']} {result.get('error', 'ok')} {result['runtime_seconds']:.1f}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
