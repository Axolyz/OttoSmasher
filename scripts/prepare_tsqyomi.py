"""Explicit, pinned model preparation in the project ONNX environment."""
import hashlib
import shutil
from huggingface_hub import hf_hub_download
from ottosmasher.g2p_frontend import MODEL
from ottosmasher.workspace import ROOT, write_json

folder = ROOT / 'models/tsqyomi'
folder.mkdir(parents=True, exist_ok=True)
for name in MODEL['files']:
    path = hf_hub_download(repo_id=MODEL['repository'], filename=MODEL['subdirectory'] + '/' + name,
                          revision=MODEL['revision'], cache_dir=str(ROOT / '.runtime/downloads/huggingface'))
    temporary = folder / (name + '.tmp')
    shutil.copyfile(path, temporary); temporary.replace(folder / name)
write_json(folder / 'preparation.json', {**MODEL, 'sha256': {name: hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in MODEL['files']}})
print(folder)
