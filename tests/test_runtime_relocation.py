import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('relocate', Path(__file__).parents[1] / 'scripts/relocate_windows_runtime.py')
relocate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relocate)


def update_function(open_file):
    # Same upstream write block, with replacement kept independent of the fix.
    source = 'def update_prefix(path, new_prefix, placeholder, mode="text"):\n' + relocate.ORIGINAL
    namespace = {'open': open_file, 'replace_prefix': lambda data, mode, old, new: data.replace(old, new)}
    exec(relocate.patched_source(source), namespace)
    return namespace['update_prefix']


def test_unchanged_loaded_dll_does_not_request_write(tmp_path):
    dll = tmp_path / '_bz2.pyd'
    dll.write_bytes(b'unchanged binary')
    modes = []

    def locked_open(path, mode):
        modes.append(mode)
        if '+' in mode:
            raise PermissionError('DLL loaded by Python')
        return open(path, mode)

    update_function(locked_open)(dll, b'new', b'old')
    assert modes == ['rb']


def test_real_replacement_is_written_and_truncated(tmp_path):
    script = tmp_path / 'entrypoint'
    script.write_bytes(b'long-old-prefix/bin/python')
    update_function(open)(script, b'new', b'long-old-prefix')
    assert script.read_bytes() == b'new/bin/python'


def test_real_write_errors_remain_fatal(tmp_path):
    script = tmp_path / 'entrypoint'
    script.write_bytes(b'old/bin/python')

    def locked_open(path, mode):
        if '+' in mode:
            raise PermissionError('cannot relocate')
        return open(path, mode)

    with pytest.raises(PermissionError, match='cannot relocate'):
        update_function(locked_open)(script, b'new', b'old')


def test_upstream_change_is_not_silently_ignored():
    with pytest.raises(RuntimeError, match='Unsupported'):
        relocate.patched_source('a different upstream implementation')
