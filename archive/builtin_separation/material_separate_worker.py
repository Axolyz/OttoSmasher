"""Isolated pymss adapter: preserve actual model stem names and every output."""

import hashlib
import json
import sys
from pathlib import Path

from pymss import MSSeparator

from ottosmasher.inference_runtime import separation_device, settings


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


from ottosmasher.workspace import ROOT, CODE_ROOT
request = Path(sys.argv[1])
p = json.loads(request.read_text())
output = Path(p["output"])
with MSSeparator.from_model_name(
    p["model"],
    download=False,
    model_dir=ROOT / "models/separation",
    **separation_device({**settings(), **({"inference_device": p["device"]} if p.get("device") else {})}),
    output_format="wav",
    store_dirs=str(output),
    inference_params={"batch_size": 1, "mps_model_backend": "torch"},
) as sep:
    supported = list(sep.config.training.instruments)
    stems = p.get("stems") or supported
    if not stems or any(s not in supported for s in stems):
        raise ValueError(f"请选择模型实际声部：{supported}")
    import subprocess

    import soundfile as sf
    from separation_chunks import separate_file

    source = p["path"]
    sr = int(sep.config.audio.get("sample_rate", 44100))
    converted = output / "input-resampled.wav"
    if sf.info(source).samplerate != sr:
        print(f"Resampling separation input to {sr} Hz", flush=True)
        from ottosmasher.workspace import executable

        ffmpeg = executable("ffmpeg")
        subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                source,
                "-ar",
                str(sr),
                "-c:a",
                "pcm_f32le",
                str(converted),
            ],
            check=True,
        )
        source = str(converted)
    files_by_stem = separate_file(sep, source, output, stems, progress_path=p.get("progress_path"))
    if converted.exists():
        converted.unlink()
    outputs = []
    p["separation_policy"] = {"version": 1, "chunk_seconds": 60, "overlap_seconds": 6, "batch_size": 1}
    print("Recording model and output provenance", flush=True)
    weights = {
        str(f.relative_to(ROOT)): digest(f)
        for f in (ROOT / "models/separation").rglob(p["model"] + ".*")
        if f.is_file()
    }
    if not weights:
        raise RuntimeError("未找到模型权重，不能登记无来源的分离版本")
    source_digest = digest(p["path"])
    for stem, file in files_by_stem.items():
        files = [file]
        if len(files) != 1:
            raise RuntimeError(f"声部 {stem} 的输出不唯一：{files}")
        outputs.append(
            {
                "path": str(files[0]),
                "model": p["model"],
                "model_fingerprints": weights,
                "stem": stem,
                "source_path": p["path"],
                "source_sha256": source_digest,
                "parameters": p,
                "verified": False,
            }
        )
    request.with_suffix(".result.json").write_text(
        json.dumps({"outputs": outputs}, ensure_ascii=False, indent=2)
    )
    (output / "manifest.json").write_text(json.dumps({"outputs": outputs}, ensure_ascii=False, indent=2))
