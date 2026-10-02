from ottosmasher.inference_runtime import onnx_session

"""Isolated CPU model worker. Raw context output is never overwritten by import."""

import argparse
import hashlib
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

import pyopenjtalk

from ottosmasher.workspace import ROOT, CODE_ROOT
sys.path.insert(0, str(CODE_ROOT / "src"))
from ottosmasher.ctc import forced_ctc


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    tmp.replace(path)


@lru_cache(maxsize=256)
def kana_phones(kana):
    return pyopenjtalk.g2p(kana).split()


def reading(text):
    kana = pyopenjtalk.g2p(text, kana=True)
    moras = []
    for c in kana:
        if c in "ァィゥェォャュョヮ" and moras:
            moras[-1] += c
        elif "\u30a1" <= c <= "\u30fa" or c == "ー":
            moras.append(c)
    raw = pyopenjtalk.g2p(text).split()
    expected, indices = [], []
    for i, m in enumerate(moras):
        ph = (
            [expected[-1]]
            if m == "ー" and expected
            else ["cl"]
            if m == "ッ"
            else ["N"]
            if m == "ン"
            else kana_phones(m)
        )
        expected.extend(ph)
        indices.extend([i] * len(ph))
    speech = [p for p in raw if p not in {"pau", "sil"}]
    vowels = set("aiueoAIUEO")
    compatible = len(expected) == len(speech) and all(
        a == b or (a in vowels and b in vowels) for a, b in zip(expected, speech)
    )
    return (
        {
            "reading": kana,
            "sequence": moras,
            "count": len(moras),
            "source": "pyopenjtalk-plus reading; no measured mora times",
            "phone_mapping": "ordered_g2p" if compatible else "unavailable",
        },
        raw,
        indices if compatible else [None] * len(speech),
    )


def transcript(item, kind):
    owners, seq, raw_records, moras = [], [], [], {}
    for c in item["context"]:
        mora, raw, indices = reading(c["spoken"])
        moras[c["id"]] = mora
        raw_records.append({"cue_id": c["id"], "phones": raw})
        j = 0
        for p in raw:
            idx = indices[j] if p not in {"pau", "sil"} else None
            j += p not in {"pau", "sil"}
            mapped = p.lower() if p in {"I", "U"} else p
            if mapped in {"pau", "sil", "cl"} and kind == "phonetic":
                mapped = "SP"
            if mapped == "sil":
                mapped = "pau"
            if kind == "phonetic" and mapped == "SP":
                continue
            seq.append(mapped)
            if mapped not in {"SP", "pau"}:
                owners.append(
                    {"phone": mapped, "cue_id": c["id"], "mora_index": idx, "reading": mora["reading"]}
                )
        if kind != "phonetic":
            seq.append("pau")
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
        sys.path.insert(0, str(ROOT / "vendor/HubertFA"))
        sys.path.insert(0, str(CODE_ROOT / "scripts"))
        from hubert_worker import CPUInference
        from praatio import textgrid

        model = ROOT / "models/hubert/1218_hfa_model_new_dict/model.onnx"
        engine = CPUInference(model)
        engine.load_config()
        engine.init_decoder()
        engine.load_model()
    elif kind == "pydomino":
        import pydomino
        import soundfile as sf

        model = ROOT / "vendor/pydomino/onnx_model/phoneme_transition_model.onnx"
        engine = pydomino.Aligner(str(model))
    else:
        import onnxruntime as ort
        import soundfile as sf
        import torch

        sys.path.insert(0, str(ROOT / "vendor/narabas"))
        from narabas.narabas import Narabas
        from narabas.symbols import BOS, EOS, phoneme_to_id

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
            if kind == "phonetic":
                import shutil

                unknown = [p for p in seq if "ja/" + p not in engine.vocab["vocab"]]
                if unknown:
                    raise ValueError(f"Unsupported HubertFA phones: {unknown}")

                wav = output.parent / "input.wav"
                shutil.copyfile(item["wav_16000"], wav)
                wav.with_suffix(".lab").write_text(" ".join(seq))
                # Upstream appends datasets/predictions. Each resumable item must
                # start empty while retaining the loaded acoustic model.
                engine.dataset = []
                engine.predictions = []
                engine.get_dataset(
                    wav_folder=output.parent, language="ja", g2p="phoneme", dictionary_path=None
                )
                if len(engine.dataset) != 1:
                    raise ValueError("HubertFA rejected the input transcript")
                engine.infer(non_lexical_phonemes="AP", pad_times=1, pad_length=5)
                engine.export(output_folder=output.parent, output_format=["textgrid"])
                tg = textgrid.openTextgrid(
                    str(output.parent / "TextGrid/input.TextGrid"), includeEmptyIntervals=False
                )
                result["phones"] = [
                    {"start": float(a), "end": float(b), "label": p.removeprefix("ja/")}
                    for a, b, p in tg.getTier("phones").entries
                ]
            elif kind == "pydomino":
                y, sr = sf.read(item["wav_16000"], dtype="float32")
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
                y, sr = sf.read(item["wav_16000"], dtype="float32")
                if sr != rate:
                    raise ValueError(f"narabas requires {rate} Hz")
                logits = engine.run(None, {"input": y[None, :]})[0]

                # Preserve the upstream decoder's output on exactly the same emissions.
                class Cached:
                    hop_length_sec = hop / rate
                    sess = type("Session", (), {"run": lambda self, *a, _logits=logits: [_logits]})()

                    def load_audio(self, path, _y=y):
                        return torch.from_numpy(_y[None, :])

                try:
                    baseline = Narabas.align(Cached(), item["wav_16000"], " ".join(seq))
                    result["upstream_baseline"] = [
                        {"start": float(a), "end": float(b), "label": p} for a, b, p in baseline
                    ]
                except Exception as exc:  # noqa: BLE001 - isolate and retain each backend failure
                    result["upstream_baseline_error"] = str(exc)
                ids = [BOS] + [phoneme_to_id[p] for p in seq] + [EOS]
                spans = forced_ctc(logits[0], ids)
                result["decoder"] = "ottosmasher-ctc-viterbi-v1; upstream baseline retained separately"
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
