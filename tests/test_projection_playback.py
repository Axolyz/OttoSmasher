import copy

import numpy as np
import soundfile as sf
from test_samples import library as library  # noqa: PLC0414
from test_reanalysis import measured

from ottosmasher import sample_analysis, sample_audio, media
from ottosmasher.workspace import identity


def test_display_rebuilds_projection_once_without_rerunning_analysis(library, monkeypatch):
    db, root, _ = library
    measured(db, root)
    db.execute("UPDATE materials SET active_phone_backend='narabas' WHERE id=?", (root['id'],))
    before = db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0]
    record = sample_analysis.display_ready(db, root['id'])
    assert record['analysis']['phones']
    assert db.execute('SELECT count(*) FROM analysis_runs').fetchone()[0] == before
    monkeypatch.setattr(sample_audio, 'pcm', lambda *_: (_ for _ in ()).throw(AssertionError('display decoded audio')))
    assert sample_analysis.display_ready(db, root['id'])['signature'] == record['signature']


def test_recreated_pcm_rebinds_whole_and_segment_lineage(library, monkeypatch, tmp_path):
    from ottosmasher.rhythm_scopes import SELECTION_VERSION
    db, root, _ = library
    measured(db, root)
    db.execute("UPDATE materials SET active_phone_backend='narabas' WHERE id=?", (root['id'],))
    record = sample_analysis.display_ready(db, root['id'])
    path = sample_audio.pcm(record['asset'])
    path.unlink()
    # Simulate a persisted pre-migration local cache recipe.
    record['cue'].update(path='retired.wav', fingerprint='retired')
    record['analysis']['audio_lineage'].update(audio_path='retired.wav', audio_sha256='retired', source_fingerprint='retired')
    segment = copy.deepcopy(record)
    segment.pop('entries', None)
    segment['analysis']['audio_selection'] = {
        'version': SELECTION_VERSION, 'parent_cue_id': root['id'],
        'source_fingerprint': 'retired', 'audio_sha256': 'retired',
        'parent_window_start': 0, 'parent_window_end': 1,
        'source_start': .2, 'source_end': .5,
    }
    selection = segment['analysis']['audio_selection']
    selection['selection_id'] = identity(SELECTION_VERSION, selection)
    record['entries'] = [segment]
    db.execute('UPDATE sample_records SET payload=? WHERE material_id=?', (sample_analysis.encode_record(record), root['id']))
    fresh = sample_analysis.ready(db, root['id'])
    assert path.is_file()
    assert fresh['signature'] == record['signature']
    monkeypatch.setattr(media, 'DATA', tmp_path / 'render')
    for entry, duration in [(fresh, 1), (fresh['entries'][0], .3)]:
        a = entry['analysis']
        output, _ = media.render(entry['cue'], variant='vocals', lineage=a['audio_lineage'], selection=a.get('audio_selection'))
        assert abs(sf.info(output).duration - duration) < 1 / 24000
        assert a['audio_lineage']['audio_path'] == str(path)


def test_concurrent_pcm_readers_observe_complete_file(library):
    from concurrent.futures import ThreadPoolExecutor
    db, root, original = library
    asset = sample_audio.resolve(db, root['id'], 'raw')
    def read(_):
        path = sample_audio.pcm(asset)
        y, _ = sf.read(path)
        return y
    with ThreadPoolExecutor(max_workers=6) as pool:
        outputs = list(pool.map(read, range(12)))
    for y in outputs:
        np.testing.assert_allclose(y, original, atol=1e-7)
    assert not list(sample_audio.DATA.rglob('*.building.wav'))


def test_virtual_shared_track_respects_file_offset(library, tmp_path, monkeypatch):
    from ottosmasher.materials import sha256
    from ottosmasher.vocals import read_aligned_input
    db, root, original = library
    cue = {**root, 'start': .1, 'end': .3, 'source_duration': 1}
    lineage = {'audio_path': root['path'], 'audio_sha256': sha256(root['path']),
               'source_fingerprint': cue['fingerprint'], 'window_start': .1, 'window_end': .3,
               'target_cue_id': cue['id'], 'audio_start': .5, 'audio_end': .7}
    monkeypatch.setattr(media, 'DATA', tmp_path / 'render')
    output, _ = media.render(cue, variant='vocals', lineage=lineage)
    y, sr = sf.read(output)
    assert len(y) == round(.2 * sr)
    assert abs(y.mean() - original[12000:16800].mean()) < 1e-4
    y, sr, start, end = read_aligned_input({'input_variant': 'vocals', 'audio_lineage': lineage,
                                         'window_start': .1, 'window_end': .3})
    np.testing.assert_allclose(y, original[12000:16800], atol=1e-7)
    assert (start, end) == (.1, .3)
