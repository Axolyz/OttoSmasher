import copy
import pytest
from test_samples import library
from ottosmasher import business_edits as edits


def test_preview_apply_undo_and_stale_document(library):
    db, root, _ = library
    doc = edits.export(db, [{"type": "sample", "id": root["id"]}])
    original = copy.deepcopy(doc)
    doc['objects'][0]['values'] = {'title': '新名称', 'tags': ['character:京子']}
    assert edits.preview(db, doc)['valid']
    assert db.execute('SELECT title FROM materials WHERE id=?', (root['id'],)).fetchone()[0] != '新名称'
    result = edits.apply(db, doc)
    assert result['valid'] and result['action_id']
    assert not edits.apply(db, original)['valid']
    undone = edits.undo(db, result['action_id'])
    assert undone['objects'][0]['values'] == original['objects'][0]['values']
    assert undone['objects'][0]['base_version'] != original['objects'][0]['base_version']


def test_invalid_second_object_rolls_back_whole_batch(library):
    from ottosmasher.sample_catalog import derive
    db, root, _ = library
    child = derive(db, root['id'], start=.2, end=.6)
    doc = edits.export(db, [{'type': 'sample', 'id': x} for x in [root['id'], child['id']]])
    doc['objects'][0]['values']['title'] = '不能写入'
    doc['objects'][1]['values']['asset_id'] = 'forbidden'
    result = edits.apply(db, doc)
    assert not result['valid']
    assert result['errors'][0]['path'] == 'objects[1]'
    assert db.execute('SELECT title FROM materials WHERE id=?', (root['id'],)).fetchone()[0] != '不能写入'


def test_old_ui_changes_invalidate_document_and_undo(library):
    db, root, _ = library
    doc = edits.export(db, [{'type': 'sample', 'id': root['id']}])
    doc['objects'][0]['values']['title'] = '第一次'
    applied = edits.apply(db, doc)
    db.execute('UPDATE materials SET title=? WHERE id=?', ('后续编辑', root['id'])); db.commit()
    with pytest.raises(ValueError, match='安全撤销'): edits.undo(db, applied['action_id'])
    assert not edits.preview(db, applied['document'])['valid']


def test_create_interval_preview_apply_and_undo(library):
    from ottosmasher import business_edits as b
    db,root,_=library
    doc=b.new_annotation(db,root['source_id'],.1,.3,tags=['effect:door'])
    db.commit()
    assert b.preview(db,doc)['valid']
    assert not db.execute('SELECT 1 FROM timeline_annotations').fetchone()
    result=b.apply(db,doc)
    assert result['valid']
    oid=doc['objects'][0]['id']
    assert db.execute('SELECT deleted FROM timeline_annotations WHERE id=?',(oid,)).fetchone()[0]==0
    b.undo(db,result['action_id'])
    assert db.execute('SELECT deleted FROM timeline_annotations WHERE id=?',(oid,)).fetchone()[0]==1


def test_promote_tags_is_previewable_atomic_and_reversible(library):
    from ottosmasher import asset_migration, timeline_labels
    db, root, _ = library
    asset_migration.activate(db)
    db.execute("INSERT INTO material_tags VALUES(?,?,'manual')", (root['id'], 'effect:door'))
    db.commit()
    draft = edits.promote_tags(db, root['id'])
    db.commit()
    assert db.execute('SELECT tag FROM material_tags WHERE material_id=?', (root['id'],)).fetchone()[0] == 'effect:door'
    result = edits.apply(db, draft)
    assert result['valid'], result
    assert not db.execute("SELECT tag FROM material_tags WHERE material_id=? AND origin='manual'", (root['id'],)).fetchone()
    assert 'effect:door' in [r['tag'] for r in timeline_labels.effective(db, [root['id']])[root['id']]]
    edits.undo(db, result['action_id'])
    assert db.execute('SELECT tag FROM material_tags WHERE material_id=?', (root['id'],)).fetchone()[0] == 'effect:door'
