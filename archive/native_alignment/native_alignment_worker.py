"""Native-granularity alignment. One model load per batch; no phone fabrication."""

import json
import sys
import time
from pathlib import Path

import soundfile as sf
import torch

from ottosmasher.inference_runtime import torch_device
from ottosmasher.workspace import ROOT, write_json


def main(request):
    spec = json.loads(request.read_text())
    kind = spec["model"]
    device = torch_device()
    started = time.monotonic()
    if kind == "yohane":
        from pykakasi import kakasi
        from yohane.audio import Wav2Vec2ForcedAligner
        from yohane.lyrics import Lyrics
        from yohane.subtitles import time_lyrics

        engine = Wav2Vec2ForcedAligner(str(ROOT / "models/yohane"), device=device)
        engine.device = torch.device(device)
        engine.model.to(device).eval()
        transliterator = kakasi()
    elif kind == "qwen3-aligner":
        from transformers import Qwen3ASRForTokenClassification, Qwen3ASRProcessor

        folder = ROOT / "models/qwen3-aligner"
        engine = (
            Qwen3ASRForTokenClassification.from_pretrained(folder, local_files_only=True).to(device).eval()
        )
        processor = Qwen3ASRProcessor.from_pretrained(folder, local_files_only=True)
    else:
        raise ValueError("未知字符/音节对齐模型")
    print(f"Stage {kind} initialization {time.monotonic() - started:.3f}s device={device}", flush=True)
    for item in spec["items"]:
        begun = time.monotonic()
        result = {
            "material_id": item["material_id"],
            "model": kind,
            "model_revision": spec.get("model_revision"),
            "adapter_version": spec.get("adapter_version"),
            "device": device,
            "input": item,
        }
        try:
            y, sr = sf.read(item["path"], dtype="float32", always_2d=True)
            if kind == "yohane":
                romanized = " ".join(x["hepburn"] for x in transliterator.convert(item["text"]))
                lyrics = Lyrics(romanized)
                tokens = engine.tokenize(lyrics.transcript)
                if not tokens or any(not t for t in tokens):
                    raise ValueError("无法建立音节到输入文本的对应")
                # Neural inference uses the requested device. CTC backtrace is a CPU postprocess.
                import librosa
                from yohane.audio import _align_token_spans

                audio = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=16000)
                inputs = engine.processor(audio=audio, sampling_rate=16000, return_tensors="pt")
                with torch.inference_mode():
                    emission = engine.model(**inputs.to(device)).logits.log_softmax(-1)[0].cpu()
                spans = _align_token_spans(emission, tokens, blank=engine.blank)
                timed = time_lyrics(
                    lyrics,
                    torch.from_numpy(audio)[None, :],
                    16000,
                    engine.tokenize,
                    emission[None, :, :],
                    spans,
                )
                segments = [
                    {"text": syl.value, "start": syl.start_s, "end": syl.end_s}
                    for line in timed
                    for syl in line
                    if syl is not None
                ]
                result.update(
                    granularity="syllable",
                    romanized=romanized,
                    text_processing="pykakasi-hepburn + yohane.Lyrics/time_lyrics",
                    alignment_units=lyrics.transcript,
                )
            else:
                import librosa

                audio = librosa.resample(y.mean(axis=1), orig_sr=sr, target_sr=16000)
                # Official Japanese morphology; do not silently substitute generic CJK characters.
                inputs, words = processor.prepare_forced_aligner_inputs(
                    audio=audio,
                    transcript=item["text"],
                    language="Japanese",
                    processor_kwargs={"return_tensors": "pt", "sampling_rate": 16000},
                )
                inputs = inputs.to(device, engine.dtype)
                with torch.inference_mode():
                    logits = engine(**inputs).logits
                raw = processor.decode_forced_alignment(
                    logits, inputs.input_ids, words, timestamp_token_id=engine.config.timestamp_token_id
                )[0]
                result.update(
                    raw=raw,
                    granularity="word",
                    language="Japanese",
                    text_processing="nagisa (official Japanese tokenizer)",
                    alignment_units=words[0],
                )
                segments = [{"text": x["text"], "start": x["start_time"], "end": x["end_time"]} for x in raw]
            duration = len(y) / sr
            if any(not 0 <= x["start"] <= x["end"] <= duration + 1 / sr for x in segments):
                raise ValueError("模型原始区间越出音频范围；结果未作为有效对齐导入")
            warnings = []
            if any(x["end"] - x["start"] < 1 / sr for x in segments):
                warnings.append("模型返回零长度区间；保留原始时间，但不能作为可播放选区")
            result.update(status="ready", segments=segments, duration=duration, warnings=warnings)
        except Exception as exc:  # noqa: BLE001 — preserve each failed item and continue this batch.
            result.update(status="failed", error=str(exc))
        result["seconds"] = time.monotonic() - begun
        write_json(Path(item["output"]), result)
        print(f"{kind} {item['material_id']} {result['status']} {result['seconds']:.3f}s", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
