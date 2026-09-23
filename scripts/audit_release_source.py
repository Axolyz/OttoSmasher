"""Check the upload set, optionally export a clean source ZIP (never an app)."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.git', '.runtime', '.venv', 'data', 'models', 'vendor', 'bangumi', 'outputs', 'work', 'node_modules', '__pycache__', 'dist', 'build', 'config'}
BINARY_DATA = {'.wav', '.flac', '.mp3', '.mp4', '.mkv', '.onnx', '.ckpt', '.pt', '.pth', '.safetensors', '.sqlite', '.sqlite3', '.db', '.pkl', '.pickle'}
SECRETS = re.compile(rb'(?:hf_[A-Za-z0-9]{25,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def inspect(path):
    if any(p in FORBIDDEN for p in path.parts) or path.name == '.env' or path.name.startswith('.env.'):
        raise ValueError(f'运行数据或私密配置不能进入软件源包：{path}')
    p = ROOT / path
    if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
        raise ValueError(f'源包不跟随链接：{path}')
    if p.suffix.lower() in BINARY_DATA or p.stat().st_size > 5 * 1024**2:
        raise ValueError(f'媒体、模型或大文件不能进入软件源包：{path}')
    data = p.read_bytes()
    if SECRETS.search(data):
        raise ValueError(f'疑似凭据，停止导出（不输出凭据内容）：{path}')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    bundled = ROOT / '.runtime/envs/core' / ('Library/bin/git.exe' if os.name == 'nt' else 'bin/git')
    git = str(bundled) if bundled.is_file() else shutil.which('git')
    if not git:
        raise SystemExit('Git is required to determine the source upload set')
    raw = subprocess.check_output([git, 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    names = sorted({Path(os.fsdecode(p)) for p in raw.split(b'\0') if p})
    entries = []
    for name in names:
        if not (ROOT / name).exists():  # staged/current deletions are not resurrected
            continue
        data = inspect(name)
        entries.append({'path': name.as_posix(), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    result = {'type': 'source-only-not-application', 'files': len(entries), 'bytes': sum(e['bytes'] for e in entries), 'entries': entries}
    if args.archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for e in entries:
                # Recheck immediately before writing; never use rglob('.') for release.
                data = inspect(Path(e['path']))
                if hashlib.sha256(data).hexdigest() != e['sha256']:
                    raise ValueError('Source changed during export; rerun the audit')
                info = zipfile.ZipInfo('OttoSmasher/' + e['path'])
                info.external_attr = ((ROOT / e['path']).stat().st_mode & 0xFFFF) << 16
                z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'entries'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
