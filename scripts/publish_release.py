"""Publish only complete, passing standard artifacts below the requested 2 GB limit."""
import hashlib
import json
import os
import subprocess
from pathlib import Path


def validate(directory, version):
    expected = {f'OttoSmasher-{version}-mac-arm64.zip', f'OttoSmasher-{version}-win-x64.zip'}
    archives = list(directory.rglob('*.zip'))
    if {p.name for p in archives} != expected or len(archives) != 2:
        raise ValueError('Both platform application ZIPs are required; unexpected ZIPs are refused')
    reports = [json.loads(p.read_text()) for p in directory.rglob('packaged-smoke.json')]
    if len(reports) != 2 or {(r.get('platform'), r.get('arch')) for r in reports} != {('darwin','arm64'),('win32','x64')} or not all(r.get('passed') for r in reports):
        raise ValueError('Both packaged smoke checks must pass')
    for p in archives:
        if not 0 < p.stat().st_size < 2_000_000_000:
            raise ValueError(f'{p.name} is not below 2 GB; release not published')
    return sorted(archives)


def main():
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root/'desktop/package.json').read_text())['version']
    archives = validate(root/'release-artifacts', version)
    sums = root/'release-artifacts/SHA256SUMS.txt'
    rows=[]
    for path in archives:
        with path.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        rows.append(f'{digest}  {path.name}')
    sums.write_text('\n'.join(rows)+'\n')
    tag='v'+version
    subprocess.run(['gh','release','create',tag,*map(str,archives),str(sums),
                    '--repo',os.environ['GITHUB_REPOSITORY'],'--target',os.environ['GITHUB_SHA'],
                    '--title','OttoSmasher '+version,'--notes-file',str(root/'RELEASE_NOTES.md')],check=True)


if __name__=='__main__':
    main()
