"""Install the official, checksum-pinned Rubber Band CLI into a specified core prefix."""
import argparse
import hashlib
import os
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HASHES = {
    'macos': '0dc91509a31a94c1144436cc20e6f1d165bdab39fe125f9be7d46139921b733f',
    'windows': 'f2d47fc64dbb42f6cc62edf7933ac4fa89d8f0ef8b9cf97b6afc263a7fe05644',
}


def install(prefix):
    system = 'windows' if os.name == 'nt' else 'macos'
    suffix = 'zip' if os.name == 'nt' else 'tar.bz2'
    name = f'rubberband-4.0.0-gpl-executable-{system}'
    cache = ROOT / 'build/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f'{name}.{suffix}'
    if not archive.is_file():
        url = f'https://breakfastquay.com/files/releases/{archive.name}'
        for attempt in range(2):
            try:
                with urllib.request.urlopen(url, timeout=60) as source, archive.with_suffix('.part').open('wb') as out:
                    shutil.copyfileobj(source, out)
                archive.with_suffix('.part').replace(archive)
                break
            except OSError:
                if attempt: raise RuntimeError(f'Download failed: {url}; save to {archive}')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != HASHES[system]:
        raise ValueError('Rubber Band checksum mismatch')
    extracted = cache / ('rubberband-' + system)
    if os.name == 'nt':
        with zipfile.ZipFile(archive) as z: z.extractall(extracted)
    else:
        with tarfile.open(archive) as t: t.extractall(extracted, filter='data')
    source = extracted / name
    binary_dir = prefix / ('Library/bin' if os.name == 'nt' else 'bin')
    binary_dir.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in ('rubberband', 'rubberband.exe', 'sndfile.dll'):
            shutil.copy2(item, binary_dir / item.name)
    notices = prefix / 'share/licenses/rubberband'
    notices.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name.startswith(('COPYING', 'README', 'CHANGELOG')):
            shutil.copy2(item, notices / item.name)
    (notices / 'SOURCE.txt').write_text('https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=ROOT / '.runtime/envs/core')
    install(parser.parse_args().prefix.resolve())
