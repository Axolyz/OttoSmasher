from ottosmasher.inference_runtime import onnx_session

"""Run pinned upstream HubertFA in its isolated ONNX environment.

No upstream edits: force CPU provider here and retain its raw TextGrid output.
Input is a prepared folder containing WAVs and source.json manifest.
"""

import argparse
import json
import sys
from pathlib import Path

from ottosmasher.workspace import ROOT, CODE_ROOT
sys.path.insert(0, str(ROOT / "vendor" / "HubertFA"))
import onnxruntime as ort
import pyopenjtalk
from onnx_infer import InferenceOnnx


class CPUInference(InferenceOnnx):
    @staticmethod
    def create_session(path):
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        return onnx_session(path, options)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.folder / "source.json").read_text())
    engine = CPUInference(args.model)
    engine.load_config()
    allowed = set(engine.vocab["vocab"])
    for cue in manifest["cues"]:
        raw = pyopenjtalk.g2p(cue["spoken"]).split()
        # This checkpoint merges geminate closure into its silence class. It cannot
        # produce an independently supervised Japanese cl interval.
        phones = [("SP" if p in {"pau", "sil", "cl"} else p.lower() if p in {"I", "U"} else p) for p in raw]
        phones = [p for p in phones if p != "SP"]
        unknown = [p for p in phones if "ja/" + p not in allowed]
        if unknown or not phones:
            raise ValueError(f"Unsupported phones for {cue['id']}: {unknown}")
        (args.folder / (cue["id"] + ".lab")).write_text(" ".join(phones), encoding="utf-8")
        cue["g2p"] = {
            "backend": "pyopenjtalk-plus",
            "raw": raw,
            "input_phones": phones,
            "mapping": "devoiced I/U to i/u; pau/sil/cl handled as model silence; no unknowns skipped",
            "closure_not_separately_aligned": "cl" in raw,
        }
    (args.folder / "prepared.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    engine.init_decoder()
    engine.load_model()
    engine.get_dataset(wav_folder=args.folder, language="ja", g2p="phoneme", dictionary_path=None)
    engine.infer(non_lexical_phonemes="AP", pad_times=1, pad_length=5)
    engine.export(output_folder=args.folder, output_format=["textgrid"])
    missing = [
        c["id"] for c in manifest["cues"] if not (args.folder / "TextGrid" / (c["id"] + ".TextGrid")).exists()
    ]
    if missing:
        raise RuntimeError(f"Missing alignments: {missing}")


if __name__ == "__main__":
    main()
