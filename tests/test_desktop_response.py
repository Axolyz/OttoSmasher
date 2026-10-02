import copy
import json
import sqlite3
import pytest
from test_samples import library
from ottosmasher import asset_timeline as a, search_sessions


def test_result_snapshot_restores_order_and_never_requeries(library):
    db,root,_=library
    selection=a.register_asset(db,root['source_id'],{'path':root['path'],'sha256':'same','start':0,'end':1,'root_knots':[[0,0],[1,1]]})
    a.bind_sample(db,root['id'],selection);db.commit()
    rows=[{'material_id':root['id'],'sample_title':'old','hits':[{'id':'hit','start':.1,'end':.3}]}]
    session=search_sessions.create(db,'pitch',{'text':'.2 A4'},{'results':rows})
    search_sessions.update(db,session['id'],{'scroll':82,'selected_id':root['id'],'active':True})
    assert search_sessions.listing(db)[0]['state']['scroll']==82
    db.execute('UPDATE materials SET title=? WHERE id=?',('renamed',root['id']));db.commit()
    restored=search_sessions.read(db,session['id'])
    assert restored['results'][0]['sample_title']=='renamed'
    assert restored['results'][0]['hits']==rows[0]['hits']
    a.bind_sample(db,root['id'],a.AssetSelection(selection.asset_id,0,.5));db.commit()
    restored=search_sessions.read(db,session['id'])
    assert restored['results'][0]['result_status']=='changed'
    assert restored['results'][0]['hits'][0]['disabled']
    search_sessions.close(db,session['id'])
    assert search_sessions.listing(db)==[]
    assert db.execute('SELECT 1 FROM materials WHERE id=?',(root['id'],)).fetchone()


def test_source_viewport_reads_multiple_runs_without_crossing_sound_identity(library):
    from ottosmasher.analysis_scope import intersecting
    db,root,_=library
    selected=a.register_asset(db,root['source_id'],{'path':root['path'],'sha256':'identity','start':0,'end':1,'root_knots':[[0,0],[1,1]]})
    for index,(lo,hi) in enumerate([(0,.4),(.6,1)]):
        rid=a.add_analysis(db,'pydomino',str(index),{'clock':'asset','phones':[{'start':lo+.01,'end':hi-.01,'label':'a'}]},selection=a.AssetSelection(selected.asset_id,lo,hi))
        a.adopt_analysis(db,'annotation',str(index),'pydomino',rid)
    phones=intersecting(db,selected.json(),'pydomino')
    assert len(phones)==2
    assert len({p['run_id'] for p in phones})==2
    cropped=intersecting(db,a.AssetSelection(selected.asset_id,.5,1).json(),'pydomino')
    assert len(cropped)==1 and cropped[0]['start']==pytest.approx(.11)
    other=a.register_asset(db,root['source_id'],{'path':root['path'],'sha256':'different','start':0,'end':1,'root_knots':[[0,0],[1,1]]})
    assert not intersecting(db,other.json(),'pydomino')


def test_bound_audio_resolution_does_not_read_full_material(library,monkeypatch):
    from ottosmasher import sample_audio,materials
    db,root,_=library
    value={'path':root['path'],'sha256':'test','start':0,'end':1,'role':'raw','root_knots':[[0,0],[1,1]]}
    db.execute('INSERT INTO sample_assets VALUES(?,?)',(root['id'],json.dumps(value)));db.commit()
    monkeypatch.setattr(materials,'get',lambda *args:pytest.fail('full material traversal'))
    assert sample_audio.resolve(db,root['id'])==value


def test_source_clip_fa_accepts_only_recorded_parent_with_one_frame_rounding(library):
    from ottosmasher.analysis_scope import intersecting
    db,root,_=library
    parent={'path':root['path'],'sha256':'parent','start':0,'end':1.00001,'sample_rate':44100,'root_knots':[[0,0],[1.00001,1]]}
    selected=a.register_asset(db,root['source_id'],{**parent,'end':1,'root_knots':[[0,0],[1,1]]})
    clip=a.register_asset(db,root['source_id'],{'path':root['path']+'.crop','sha256':'crop','start':0,'end':.4,'root_knots':[[0,.1],[.4,.5]],'provenance':{'version':'whole-vocal-clip-v1','window_start':.1,'window_end':.5,'full_source_asset':parent}})
    rid=a.add_analysis(db,'pydomino','test',{'phones':[{'start':.2,'end':.3,'label':'a'}]},selection=clip)
    a.adopt_analysis(db,'annotation','clip','pydomino',rid)
    phones=intersecting(db,selected.json(),'pydomino')
    assert len(phones)==1 and abs(phones[0]['start']-.2)<1/44100
    wrong=a.register_asset(db,root['source_id'],{**parent,'sha256':'other'})
    assert not intersecting(db,wrong.json(),'pydomino')


def test_job_summary_does_not_embed_large_results(library,monkeypatch):
    from ottosmasher import operation_jobs,workspace
    db,root,_=library
    # The fixture uses the workspace's own database; never launch a worker.
    db.execute("INSERT INTO operation_jobs(id,operation,payload,status,result,error,pid,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",('summary-test','flatten',json.dumps({'material_id':root['id']}),'succeeded',json.dumps({'sample':{'id':'output'},'frames':[1]*10000}),None,None,1,1));db.commit()
    rows=operation_jobs.listing(summary=True)
    row=next(r for r in rows if r['id']=='summary-test')
    assert 'frames' not in row['result']
    assert row['result']['sample_id']=='output'
    assert root['id'] in row['affected']['sample_ids']
    assert root['source_id'] in row['affected']['source_ids']
