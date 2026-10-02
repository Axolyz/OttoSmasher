import json
import pytest
from test_samples import library
from ottosmasher import phone_timing, asset_timeline as a, reanalysis
from ottosmasher.sample_inference import attach_text
from ottosmasher.sample_audio import resolve
from ottosmasher.workspace import identity


def measured(db,root):
    attach_text(db,root['id'],'ああ')
    asset=resolve(db,root['id'],'raw')
    db.execute('INSERT INTO sample_assets VALUES(?,?)',(root['id'],json.dumps(asset)))
    selection=a.register_asset(db,root['source_id'],asset)
    payload={'clock':'asset','version':'fixture','input_selection':selection.json(),'input_descriptor_signature':identity(asset),
      'phones':[{'label':'a','start':.1,'end':.4,'mora_index':0},{'label':'a','start':.4,'end':.8,'mora_index':1}]}
    rid=a.add_analysis(db,'narabas','fixture',payload,selection=selection)
    a.adopt_analysis(db,'sample',root['id'],'narabas',rid);db.commit()
    return rid


def test_manual_timestamps_keep_labels_mora_and_protect_head(library):
    db,root,_=library; rid=measured(db,root)
    doc=phone_timing.document(db,root['id'])
    changed={**doc,'text':'.1 .5 a\n.5 .8 a'}
    result=phone_timing.apply(db,changed)
    new=json.loads(db.execute('SELECT payload FROM analysis_runs WHERE id=?',(result['run_id'],)).fetchone()[0])
    assert [p['mora_index'] for p in new['phones']]==[0,1]
    assert a.adopt_analysis(db,'sample',root['id'],'narabas',rid,automatic=True)['reason']=='human_timing'
    db.commit()
    with pytest.raises(ValueError,match='版本'):phone_timing.apply(db,doc)
    latest=phone_timing.document(db,root['id'])
    with pytest.raises(ValueError,match='标签'):phone_timing.apply(db,{**latest,'text':'.1 .5 i\n.5 .8 a'})
    assert len(phone_timing.versions(db,root['id'],'narabas'))==2


def test_snapshot_freezes_current_audio_and_reports_missing_text(library):
    db,root,_=library
    assert reanalysis.snapshot(db,[root['id']])['missing']
    measured(db,root)
    s=reanalysis.snapshot(db,[root['id']],'pydomino')
    assert not s['missing']
    assert s['items'][0]['asset']['path']==root['path']
    assert s['items'][0]['backend']=='pydomino'
    assert s['items'][0]['padding_requested']==[.65,.65]
    assert s['items'][0]['selection']['asset_id']


def test_asset_fa_snapshot_needs_no_saved_sample(library,monkeypatch):
    from ottosmasher import reanalysis as fa,selection_ops,operation_jobs,asset_timeline as t
    db,root,_=library
    selection=selection_ops.from_sample(db,root['id'],.2,.7)
    db.execute('INSERT INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)',('standalone-text',root['source_id'],.2,.7,'dialogue','ねえ','[]','{"type":"source","ids":[]}'))
    db.commit()
    captured=[]
    monkeypatch.setattr(operation_jobs,'submit',lambda operation,payload:captured.append((operation,payload)) or {'id':'test'})
    before=db.execute('SELECT count(*) FROM materials').fetchone()[0]
    response=fa.submit_selection(db,selection.json(),'standalone-text','pydomino')
    assert response['job']['id']=='test'
    assert db.execute('SELECT count(*) FROM materials').fetchone()[0]==before
    item=captured[0][1]['items'][0]
    assert item['owner_type']=='asset_text'
    assert item['alignment']['text']=='ねえ'
    assert item['selection']['asset_id']==selection.asset_id


def test_choosing_version_updates_shared_active_head(library):
    from ottosmasher.analysis_scope import covering
    db, root, _ = library
    original = measured(db, root)
    changed = phone_timing.document(db, root['id'])
    human = phone_timing.apply(db, {**changed, 'text': '.1 .5 a\n.5 .8 a'})
    assert covering(db, resolve(db, root['id']), 'narabas')['id'] == human['run_id']
    revision = db.execute("SELECT revision FROM analysis_references WHERE owner_type='sample' AND owner_id=? AND kind='narabas'", (root['id'],)).fetchone()[0]
    assert phone_timing.choose(db, root['id'], 'narabas', original, revision)['adopted']
    assert covering(db, resolve(db, root['id']), 'narabas')['id'] == original
