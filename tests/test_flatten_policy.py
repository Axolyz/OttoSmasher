import numpy as np
import pytest
from ottosmasher.flatten_pitch import regions, target_note
from test_samples import library


def frames():
    t = np.arange(.005, 1, .01)
    return {'times':t.tolist(), 'f0_hz':np.where(t<.5,440,660).tolist(),
            'confidence':[.9]*100,'voiced':[True]*100,'energy':[.1]*100}


def test_boundary_side_and_halfstep():
    f=frames()
    left, span=target_note(f, [[.2,.8]], strategy='boundary')
    right, other=target_note(f, [[.2,.8]], strategy='boundary',side='right')
    assert left['midi']==69 and right['midi']==76
    assert span==pytest.approx([.2,.3]) and other==pytest.approx([.7,.8])
    f['confidence'][:30]=[0]*30
    with pytest.raises(ValueError,match='换侧'):
        target_note(f,[[.2,.8]],strategy='boundary')
    assert target_note(f,[[.2,.8]],strategy='boundary',side='right')[0]['midi']==76


def test_first_vowel_tail_and_manual_bounds():
    f=frames(); f['energy'][:30]=[0]*30
    assert regions('from_first_vowel',1,[[.2,.5],[.7,.8]],f,True)==[[.2,1]]
    assert regions('from_first_vowel',1,[[.2,.5],[.7,.8]],f)[0][0]>.2
    assert regions('vowels',1,[[.2,.5],[.7,.8]],f,True)==[[.2,.5],[.7,.8]]
    assert regions('from_first_vowel',1,[[0,.2]],frames(),True)==[[0,1]]
    with pytest.raises(ValueError): regions('from_first_vowel',1,[],f)


def test_silent_and_invalid_manual():
    f=frames(); f['voiced']=[False]*100
    with pytest.raises(ValueError): target_note(f,[[0,1]])
    with pytest.raises(ValueError): target_note(f,[[0,1]],strategy='manual')
    assert target_note(None,[[0,1]],target='C4',strategy='manual')[0]['midi']==60


def test_single_tag_intersects_saved_scope_and_expression(library):
    from ottosmasher.sample_scope import ids
    db,root,_=library
    db.execute("INSERT INTO material_tags VALUES(?,?,'manual')",(root['id'],'test:a'))
    db.execute("INSERT INTO material_tags VALUES(?,?,'manual')",(root['id'],'test:b'))
    scope={'single_tag':'test:a','tag_expression':'"test:b"','intersections':[{'material_ids':[root['id']]}]}
    assert ids(db,scope)==[root['id']]
    assert ids(db,{**scope,'tag_expression':'NOT "test:b"'})==[]
    assert ids(db,{**scope,'single_tag':'unknown'})==[]
    assert ids(db,{**scope,'single_tag':None})==[root['id']]


def test_legacy_sample_measurement_requires_same_sound_and_mapping(monkeypatch):
    from ottosmasher import sample_analysis
    from ottosmasher.flatten_pitch import sample_measurement,phone_ranges
    from ottosmasher import analysis_scope
    asset={'path':'same.wav','sha256':'same','audio_stream':0,'start':10,'end':11,'root_knots':[[0,20],[1,21]]}
    record={'asset':asset,'analysis':{'phones':[{'label':'n','start':0,'end':.2},{'label':'N','start':.2,'end':.7}], 'manual_timing':True}}
    monkeypatch.setattr(sample_analysis,'ready',lambda *a,**k:record)
    monkeypatch.setattr(analysis_scope,'covering',lambda *a:None)
    assert sample_measurement(None,asset,'sample','narabas')[1]==0
    assert phone_ranges(None,asset,'narabas','sample')==([[.2,.7]],True)
    assert sample_measurement(None,{**asset,'sha256':'changed'},'sample','narabas') is None
    assert sample_measurement(None,{**asset,'root_knots':[[0,30],[1,31]]},'sample','narabas') is None


def test_preview_rejects_empty_manual_target_without_cached_frames(monkeypatch):
    from ottosmasher import flatten_preview as module
    from ottosmasher.asset_timeline import AssetSelection
    monkeypatch.setattr(module, 'resolve', lambda *a: (AssetSelection('a',0,1), {'role':'raw'}))
    monkeypatch.setattr(module, 'cached_asset', lambda *a: {'frames': None})
    with pytest.raises(ValueError, match='目标音高'):
        module.preview(None, {}, pitch_strategy='manual')
    assert module.preview(None, {})['status'] == 'pending'
