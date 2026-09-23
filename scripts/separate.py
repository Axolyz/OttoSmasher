"""Optional separation experiment; run with the isolated separation Python."""

import argparse
import json
import time
from pathlib import Path

from pymss import MSSeparator

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="becruily_deux")
    parser.add_argument("--device", default="auto", choices=["auto", "mps", "cuda", "cpu"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with MSSeparator.from_model_name(
        args.model,
        download=True,
        source="huggingface",
        model_dir=ROOT / "models/separation",
        device=args.device,
        output_format="wav",
        store_dirs=str(args.output),
    ) as separator:
        separator.process_folder(str(args.input))
    (args.output / "separation.json").write_text(
        json.dumps(
            {
                "input": str(args.input.resolve()),
                "model": args.model,
                "device": args.device,
                "seconds": time.time() - started,
                "verified": False,
                "purpose": "separation experiment; source audio retained",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
