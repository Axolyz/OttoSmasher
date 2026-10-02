"""Explicit developer-only restoration of the original local PyMSS adapter."""
import json
import subprocess
from pathlib import Path
from ottosmasher.workspace import ROOT, CODE_ROOT
from ottosmasher.inference_runtime import python_path
from ottosmasher.materials import sha256

def models():
    return [{"name": name, "stems": ["vocals", "instrument"]} for name in ("becruily_deux", "bs_roformer_voc_hyperacev2") if list((ROOT / "models/separation").rglob(name + ".ckpt"))]
def stems(model): return model["stems"]
def fingerprint(name):
    files = {str(p.relative_to(ROOT)): sha256(p) for p in (ROOT / "models/separation").rglob(name + ".*") if p.is_file()}
    if not files: raise ValueError("内置 PyMSS 权重缺失")
    return {"provider": "builtin", "model": name, "files": files}
def separate_many(name, inputs, output, selected_stems=None, device="auto", progress_path=None):
    results=[]
    for i,path in enumerate(inputs):
        folder=Path(output)/str(i);folder.mkdir(parents=True,exist_ok=True)
        req=folder/"request.json"
        req.write_text(json.dumps({"model":name,"path":str(path),"output":str(folder),"stems":selected_stems,"device":device,"progress_path":str(progress_path) if progress_path else None}))
        subprocess.run([str(python_path("torch")),str(CODE_ROOT/"archive/builtin_separation/material_separate_worker.py"),str(req)],check=True)
        rows=json.loads(req.with_suffix(".result.json").read_text())["outputs"]
        for row in rows: row.update(provider="builtin",model_fingerprints={**fingerprint(name),"requested_device":device})
        results.append(rows)
    return results
