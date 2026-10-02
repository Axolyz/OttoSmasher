import json
import subprocess
from pathlib import Path
import pytest
from test_samples import library
from ottosmasher import visual_media as v,business_edits as edits
from ottosmasher.workspace import executable


def make_visual(path,seconds=None):
    args=[executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=blue:s=32x32:r=20']
    args+=['-t',str(seconds),'-c:v','libx264','-pix_fmt','yuv420p'] if seconds else ['-frames:v','1']
    subprocess.run([*args,str(path)],check=True)


def test_image_loop_thumbnail_export_and_saved_undo(library,tmp_path):
    from ottosmasher.sample_thumbnails import thumbnail
    db,root,_=library
    image=tmp_path/'still.png';make_visual(image)
    doc=edits.export(db,[{'type':'source_visual','id':root['source_id']}]);db.commit()
    doc['objects'][0]['values']={'mode':'image','path':str(image)}
    result=edits.apply(db,doc)
    assert result['valid']
    binding=v.playback(db,root['id'])
    assert binding['mode']=='image' and binding['inherited']
    assert Path(thumbnail(db,root['id'])).is_file()
    exported=v.export(db,root['id'])
    assert json.loads(Path(exported['path']).read_text())['visual']['mode']=='image'
    edits.undo(db,result['action_id'])
    assert v.effective(db,root['id']) is None
    movie=tmp_path/'loop.mp4';make_visual(movie,.6)
    doc=edits.export(db,[{'type':'sample_visual','id':root['id']}]);db.commit()
    doc['objects'][0]['values']={'mode':'local_loop','path':str(movie)}
    assert edits.apply(db,doc)['valid']
    binding=v.effective(db,root['id'])
    assert v.position(binding,1.45)==pytest.approx(.25)
    key=v.register(binding)
    assert v.browser_file(key).is_file()
    assert v.export(db,root['id'])['manifest']['loop_rule']=='sample_local_time % visual.duration'


def test_sync_position_uses_piecewise_source_mapping():
    binding={'mode':'sync','root_knots':[[0,10],[.5,11],[1,14]]}
    assert v.position(binding,.75)==12.5
    with pytest.raises(ValueError):v.position(binding,2)
