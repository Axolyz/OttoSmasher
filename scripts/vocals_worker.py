"""One pymss model session, explicit vocals stem, independent outputs per clip."""

import json
import sys
from pathlib import Path

from pymss import MSSeparator

from ottosmasher.inference_runtime import separation_device

from ottosmasher.workspace import ROOT, CODE_ROOT


def main():
    server = sys.argv[1] == "--server"
    request = sys.stdin.readline().strip() if server else sys.argv[1]
    entries = json.loads(Path(request).read_text())["entries"]
    loaded_model = entries[0]["model"]
    with MSSeparator.from_model_name(
        entries[0]["model"],
        download=False,
        model_dir=ROOT / "models/separation",
        **separation_device(),
        output_format="wav",
        inference_params={"mps_model_backend": "torch"},
        store_dirs={"vocals": str(Path(entries[0]["folder"]) / "stems")},
    ) as sep:
        vocal_stem = next((s for s in sep.config.training.instruments if s.lower() == "vocals"), None)
        if vocal_stem is None:
            raise RuntimeError("Configured model does not provide the required vocals stem")
        while request:
            try:
                for entry in entries:
                    if entry["stem"] != "vocals" or entry["model"] != loaded_model:
                        raise ValueError("Batch model/stem mismatch")
                    output = Path(entry["folder"]) / "stems"
                    output.mkdir(exist_ok=True)
                    sep.store_dirs = {vocal_stem: str(output)}
                    import soundfile as sf

                    cached = output / "context_vocals.wav"
                    if (
                        not cached.exists()
                        or abs(sf.info(cached).duration - sf.info(entry["input_path"]).duration) > 0.01
                    ):
                        sep.process_folder(entry["input_path"])
                        produced = output / f"context_{vocal_stem}.wav"
                        if produced != cached and produced.exists():
                            produced.replace(cached)
                    if not (output / "context_vocals.wav").is_file():
                        raise RuntimeError(f"Missing vocals for {entry['cue_id']}")
                    print(f"Completed vocals: {entry['cue_id']}", flush=True)
                status = {"ok": True}
            except Exception as exc:  # noqa: BLE001 - report model failures per request
                status = {"ok": False, "error": str(exc)}
            if server:
                result = Path(request).with_suffix(".result.json")
                temporary = result.with_suffix(".tmp")
                temporary.write_text(json.dumps(status))
                temporary.replace(result)
                request = sys.stdin.readline().strip()
                if request:
                    entries = json.loads(Path(request).read_text())["entries"]
            else:
                if not status["ok"]:
                    raise RuntimeError(status["error"])
                break


if __name__ == "__main__":
    main()
