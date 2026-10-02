"""Prepare weight-free G2P imports and the dictionary in the isolated runtime."""
import importlib.util
from pathlib import Path


def prepare():
    # Upstream eagerly imports unused legacy yomi sessions. Keep the old feature's
    # semantics but defer that import until explicitly requested. tsqyomi bypasses it.
    spec = importlib.util.find_spec('pyopenjtalk')
    path = Path(spec.origin).with_name('utils.py')
    original = 'from .yomi_model.nani_predict import predict'
    replacement = '''def predict(*args, **kwargs):
    from .yomi_model.nani_predict import predict as legacy_predict
    return legacy_predict(*args, **kwargs)'''
    source = path.read_text(encoding='utf-8')
    if original in source:
        path.write_text(source.replace(original, replacement, 1), encoding='utf-8')
    elif replacement not in source:
        raise RuntimeError('Unsupported pyopenjtalk legacy import; integration patch must be reviewed')
    import pyopenjtalk
    assert pyopenjtalk.g2p('\u3042', use_sudachi_kanji_yomi=False, predict_nani=False), 'OpenJTalk dictionary is unavailable'
    print('OpenJTalk dictionary ready; legacy model import is lazy')


if __name__ == '__main__':
    prepare()
