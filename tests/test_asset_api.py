from fastapi.testclient import TestClient
from test_samples import library
from ottosmasher.api import app
from ottosmasher import asset_timeline as t,asset_migration


def test_resolved_selection_survives_request_and_business_edit(library):
    db,root,_=library
    asset_migration.activate(db)
    with TestClient(app) as client:
        response=client.post('/api/samples/selection/resolve',json={'material_id':root['id'],'start':.1,'end':.4})
        assert response.status_code==200,response.text
        selection=response.json()
        assert t.selection_asset(db,t.AssetSelection(**selection))['start']==.1
        draft=client.post('/api/samples/selection/new-annotation',json={'selection':selection,'kind':'event','text':'（足音）'}).json()
        saved=client.post('/api/samples/edit/apply',json=draft)
        assert saved.status_code==200 and saved.json()['valid'],saved.text
        row=client.post('/api/samples/selection/save',json={'selection':selection}).json()
        assert row['title']=='（足音）'
        assert row['asset_selection']['asset_id']==selection['asset_id']


def test_raw_source_selections_share_asset(library):
    from ottosmasher.selection_ops import from_source
    db, root, _ = library
    asset_migration.activate(db)
    first = from_source(db, root['id'], .1, .4)
    second = from_source(db, root['id'], .3, .8)
    assert first.asset_id == second.asset_id
    assert (first.start, first.end) == (.1, .4)


def test_query_invalid_options_fail_even_with_empty_scope(library):
    db, _, _ = library
    with TestClient(app) as client:
        for params in [{'boundaries': {'start_tolerance': -1}}, {'roles': 'vocals'}, {'arbitrary': 1}]:
            response = client.post('/api/samples/pitch-query', json={'text': '.4 A4', **params})
            assert response.status_code == 400, response.text
