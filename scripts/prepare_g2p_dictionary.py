"""Materialize the OpenJTalk dictionary at build time, with ASCII-only process argv."""
import pyopenjtalk

if __name__ == '__main__':
    assert pyopenjtalk.g2p('\u3042'), 'OpenJTalk dictionary is unavailable'
    print('OpenJTalk dictionary ready')
