"""Reapply small tracked integration patches to pinned third-party checkouts."""

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OTTO_ROOT", CODE_ROOT)).resolve()


def main():
    p = ROOT / "vendor/pymss/pyproject.toml"
    s = p.read_text()
    s = (
        "\n".join(
            line for line in s.splitlines() if not ("mlx" in line and ("darwin" in line or "mlx>=" in line))
        )
        + "\n"
    )
    p.write_text(s)
    p = ROOT / "vendor/pymss/pymss/separator.py"
    s = p.read_text()
    # All application entrypoints choose Torch explicitly. Disable upstream auto MLX selection too.
    s = s.replace(
        'inference_params.setdefault("mps_model_backend", "mlx_full")',
        'inference_params.setdefault("mps_model_backend", "torch")',
    )
    import ast

    lines = s.splitlines(True)
    for n in ast.parse(s).body:
        if isinstance(n, ast.FunctionDef) and n.name == "_prefer_mlx_for_auto":
            lines[n.lineno - 1 : n.end_lineno] = [
                'def _prefer_mlx_for_auto(requested_device, selected_device, inference_params, logger):\n    inference_params["mps_model_backend"] = "torch"\n    return inference_params\n'
            ]
            break
    p.write_text("".join(lines))

    p = ROOT / "vendor/yohane/yohane/audio.py"
    s = p.read_text().replace(
        "def __init__(self, model: str) -> None:",
        'def __init__(self, model: str, device: str = "cpu") -> None:',
    )
    start = s.index("class Wav2Vec2ForcedAligner")
    end = s.index("    def ", s.index("    def ", start) + 8)
    chunk = s[start:end].replace(
        'torch.device("cuda" if torch.cuda.is_available() else "cpu")', "torch.device(device)"
    )
    p.write_text(s[:start] + chunk + s[end:])


if __name__ == "__main__":
    main()
