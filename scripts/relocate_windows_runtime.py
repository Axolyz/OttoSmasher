"""Run conda-pack relocation without requesting writes to unchanged loaded DLLs.

conda-pack 0.9.2 opens every prefix record rb+, including Python's loaded
extension DLLs. Windows denies that open even when no replacement is needed.
Keep the generated script and all its replacement rules, but delay opening for
write until its own replace_prefix reports a real change. Genuine write errors
still fail startup. Fail closed if the pinned upstream implementation changes.
"""
import sys
from pathlib import Path


ORIGINAL = """    file_changed = False
    with open(path, 'rb+') as fh:
        original_data = fh.read()
        fh.seek(0)

        data = replace_prefix(original_data, mode, placeholder, new_prefix)

        # If the before and after content is the same, skip writing
        if data != original_data:
            fh.write(data)
            fh.truncate()
            file_changed = True
"""

READ_BEFORE_WRITE = """    with open(path, 'rb') as fh:
        original_data = fh.read()
    data = replace_prefix(original_data, mode, placeholder, new_prefix)
    file_changed = data != original_data
    if file_changed:
        with open(path, 'rb+') as fh:
            fh.write(data)
            fh.truncate()
"""


def patched_source(source):
    if source.count(ORIGINAL) != 1:
        raise RuntimeError('Unsupported conda-unpack implementation; rebuild with conda-pack 0.9.2')
    return source.replace(ORIGINAL, READ_BEFORE_WRITE)


def main(script):
    script = Path(script).resolve()
    source = patched_source(script.read_text(encoding='utf-8'))
    sys.argv = [str(script)]
    sys.path.insert(0, str(script.parent))
    exec(compile(source, str(script), 'exec'), {'__name__': '__main__', '__file__': str(script)})


if __name__ == '__main__':
    main(sys.argv[1])
