"""Isolated model inference; request/result files, never imports the catalog."""

import json
import os
import sys
import time
from pathlib import Path

from ottosmasher.inference_runtime import separation_device, settings

from ottosmasher.workspace import ROOT, CODE_ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models/huggingface"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def main(req):
    import torch

    torch.set_num_threads(4)

    weights = ROOT / "models/sound-lab"
    op = req["operation"]
    out = Path(req["output"])
    out.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    if op == "bandit-v2":
        from pymss import MSSeparator

        result = []
        with MSSeparator(
            model_type="bandit_v2",
            model_path=weights / op / "model.ckpt",
            config_path=weights / op / "config.yaml",
            **separation_device({**settings(), **({"inference_device": req["device"]} if req.get("device") else {})}),
            output_format="wav",
            use_tta=True,
            inference_params={"batch_size": 1, "mps_model_backend": "torch"},
            store_dirs=str(out),
        ) as sep:
            for i, path in enumerate(req["paths"]):
                stems = {s: out / str(i) / s for s in sep.config.training.instruments}
                for p in stems.values():
                    p.mkdir(parents=True, exist_ok=True)
                sep.store_dirs = {s: str(p) for s, p in stems.items()}
                progress_path = req.get("progress_path")
                last_report = [0.0]
                tta_state = {"pass": 0, "done": 0}

                def progress(
                    done, count, message="", i=i, last_report=last_report,
                    progress_path=progress_path, tta_state=tta_state
                ):
                    now = time.monotonic()
                    finished = message == "窗口完成"
                    if done < tta_state["done"]:
                        tta_state["pass"] += 1
                    tta_state["done"] = done
                    if now - last_report[0] < 1 and done < count:
                        return
                    last_report[0] = now
                    pass_fraction = min(1, max(0, done / max(count, 1)))
                    # pymss runs original, channel-reversed and polarity-inverted audio for TTA.
                    fraction = 1 if finished else min(1, (tta_state["pass"] + pass_fraction) / 3)
                    value = {
                        "stage": "separation",
                        "window": i + 1,
                        "windows": len(req["paths"]),
                        "window_percent": round(fraction * 100, 1),
                        "tta_pass": min(3, tta_state["pass"] + 1),
                        "percent": round(100 * (i + fraction) / len(req["paths"]), 1),
                        "elapsed": round(now - t, 1),
                        "message": message,
                        "updated": time.time(),
                    }
                    if progress_path:
                        p = Path(progress_path)
                        p.parent.mkdir(parents=True, exist_ok=True)
                        tmp = p.with_suffix(".tmp")
                        tmp.write_text(json.dumps(value))
                        tmp.replace(p)
                    print(
                        f"BandIt {i + 1}/{len(req['paths'])} · {fraction * 100:.1f}% · {message}", flush=True
                    )

                sep.progress_callback = progress
                progress(0, 1, "分离中")
                if not sep.process_folder(path):
                    raise RuntimeError("BandIt 分离失败，不回退混音")
                progress(1, 1, "窗口完成")
                files = {}
                aliases = {"speech": "dialog", "music": "music", "effects": "effect", "sfx": "effect"}
                for s, p in stems.items():
                    paths = list(p.glob("*.wav"))
                    if len(paths) != 1:
                        raise RuntimeError("BandIt 输出不唯一")
                    files[aliases[s.lower()]] = str(paths[0])
                result.append(files)
        return {"outputs": result, "seconds": time.monotonic() - t, "tta": True}
    raise ValueError("Unsupported model operation " + op)


if __name__ == "__main__":
    reqpath = Path(sys.argv[1])
    req = json.loads(reqpath.read_text())
    r = main(req)
    import psutil
    r["peak_rss_bytes"] = psutil.Process().memory_info().rss
    r["platform"] = sys.platform
    reqpath.with_suffix(".result.json").write_text(json.dumps(r))
