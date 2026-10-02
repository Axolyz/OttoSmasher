"""Chunked FCPE indexing; one model instance for the entire explicit job."""

import json
import math
import shutil
import sys
import uuid
from pathlib import Path
import numpy as np
import soundfile as sf

from ottosmasher.workspace import DATA, command, executable, write_json
from ottosmasher.materials import sha256
from ottosmasher.pitch_search import write_index
from ottosmasher.sound_features import FCPE

request = json.loads(Path(sys.argv[1]).read_text())
results = []
model = None
for track in request["tracks"]:
    result = dict(track)
    temporary = None
    try:
        folder = Path(track.get("index_path") or DATA / "pitch-index" / track["id"])
        manifest = folder / "manifest.json"
        if manifest.is_file():
            saved = json.loads(manifest.read_text())
            if (
                saved.get("file_stat") == track["file_stat"]
                and saved.get("signature") == track["signature"]
                and (folder / "native.npy").is_file()
                and (folder / "summary.npy").is_file()
            ):
                result.update(index_path=str(folder), frames=saved["frames"])
                results.append(result)
                continue
        if sha256(track["path"]) != track["sha256"]:
            raise ValueError("声音文件内容已改变，索引未复用旧指纹")
        temporary = folder.with_name(folder.name + ".tmp-" + uuid.uuid4().hex)
        temporary.mkdir(parents=True, exist_ok=True)
        audio = temporary / "mono.wav"
        command(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-i",
                track["path"],
                "-map",
                f"0:{track['audio_stream']}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_f32le",
                audio,
            ]
        )
        if model is None:
            model = FCPE()
        with sf.SoundFile(audio) as source:
            count = math.ceil(source.frames / 160)
            values = np.lib.format.open_memmap(
                temporary / "building.npy", mode="w+", dtype="float32", shape=(count, 3)
            )
            values[:] = 0
            for begin in range(0, source.frames, 60 * 16000):
                end = min(source.frames, begin + 60 * 16000)
                lo = max(0, begin - 16000)
                hi = min(source.frames, end + 16000)
                source.seek(lo)
                wave = source.read(hi - lo, dtype="float32")
                frames = model.infer(wave, 16000)
                start_frame = round((begin - lo) / 160)
                length = min(math.ceil((end - begin) / 160), len(frames["f0_hz"]) - start_frame)
                chunk = np.column_stack(
                    [frames[k][start_frame : start_frame + length] for k in ("f0_hz", "confidence", "energy")]
                )
                values[begin // 160 : begin // 160 + length] = chunk
            values.flush()
            n = write_index(temporary, values[:, 0], values[:, 1], values[:, 2])
            del values
        audio.unlink()
        (temporary / "building.npy").unlink()
        write_json(
            temporary / "manifest.json",
            {
                "signature": track["signature"],
                "file_stat": track["file_stat"],
                "frames": n,
                "model": request["model"],
            },
        )
        # Never mutate files held by a reader; publish a distinct generation.
        generation = folder.with_name(folder.name + "-" + uuid.uuid4().hex[:8])
        temporary.replace(generation)
        temporary = None
        result.update(index_path=str(generation), frames=n)
    except Exception as e:
        result["error"] = str(e)
    finally:
        if temporary and temporary.exists():
            shutil.rmtree(temporary)
    results.append(result)
    print("Pitch index", track["id"], result.get("error", "ready"), flush=True)
write_json(Path(sys.argv[2]), {"tracks": results})
