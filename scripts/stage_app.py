"""Stage an allowlisted core application. Never copy a working .runtime or models wholesale."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage(core, player, target):
    import conda_pack
    target.mkdir(parents=True, exist_ok=True)
    software = target / 'software'
    if software.exists():
        shutil.rmtree(software)
    software.mkdir()
    for folder in ('src', 'scripts', 'dependencies'):
        shutil.copytree(ROOT / folder, software / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'desktop/dist', software / 'desktop/dist')
    for name in ('ottosmasher.png', 'pyproject.toml', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, software / name)
    runtime = target / 'runtime'
    runtime.mkdir(exist_ok=True)
    files = []
    for name, prefix in [('core', core), ('player', player)]:
        if prefix is None:
            continue
        archive = runtime / f'{name}.tar.gz'
        conda_pack.pack(prefix=str(prefix.resolve()), output=str(archive), force=True,
                        ignore_editable_packages=False, n_threads=2)
        files.append({'name': archive.name, 'target': name, 'sha256': digest(archive)})
    native = []
    for name in ['player.node'] + (['mpv-2.dll'] if platform.system() == 'Windows' else []):
        shutil.copy2(ROOT / '.runtime' / name, runtime / name)
        if name == 'player.node' and platform.system() == 'Darwin':
            load_commands = subprocess.check_output(['otool', '-l', str(runtime / name)], text=True)
            for rpath in re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset', load_commands):
                if rpath.startswith('/'):
                    subprocess.run(['install_name_tool', '-delete_rpath', rpath, str(runtime / name)], check=True)
            subprocess.run(['codesign', '--force', '--sign', '-', str(runtime / name)], check=True)
        native.append({'name': name, 'sha256': digest(runtime / name)})
    # Include code in the runtime ID so the service cannot reuse a stale backend.
    code_hash = hashlib.sha256()
    for p in sorted(software.rglob('*')):
        if p.is_file():
            code_hash.update(p.relative_to(software).as_posix().encode())
            code_hash.update(p.read_bytes())
    manifest = {'platform': 'win32' if platform.system() == 'Windows' else 'darwin',
                'arch': 'x64' if platform.system() == 'Windows' else 'arm64',
                'files': files, 'native': native, 'code_sha256': code_hash.hexdigest()}
    manifest['id'] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:20]
    (runtime / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'stage': str(target), 'id': manifest['id']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, default=ROOT / '.runtime/envs/core')
    parser.add_argument('--player', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/app')
    args = parser.parse_args()
    stage(args.core, args.player, args.output)
