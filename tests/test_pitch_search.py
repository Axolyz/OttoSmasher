import numpy as np
import pytest
from ottosmasher.pitch_search import parse,write_index,search_tracks,valid_starts,options


def track(tmp_path,f0,ranges=None,confidence=None):
    f0=np.array(f0);count=len(f0)
    write_index(tmp_path,f0,np.ones(count) if confidence is None else confidence,np.full(count,.01))
    return {'id':'audio','path':str(tmp_path),'frames':count,'ranges':ranges or [(0,count*.01)]}


def test_pitch_queries_are_quantized_and_bounded():
    assert parse('0.404 A4\n.3 C5..D5')[0]['frames']==40
    for text in ['.09 A4','11 C4','.4 G5..C4','.4 H9','']:
        with pytest.raises(ValueError):parse(text)
    with pytest.raises(ValueError):options({'confidence':.1})


def test_single_and_multi_note_exact_refinement(tmp_path):
    t=track(tmp_path,np.r_[np.full(40,440.),np.full(30,523.251)])
    result=search_tracks([t],'.4 A4\n.3 C5')
    assert result['results'][0]['start']==0
    assert result['results'][0]['end']==pytest.approx(.7)
    assert not search_tracks([t],'.4 F2')['results']


def test_never_stitch_adjacent_samples(tmp_path):
    t=track(tmp_path,np.full(100,440),[(0,.5),(.5,1)])
    assert not search_tracks([t],'.6 A4')['results']
    assert valid_starts([(0,.5),(.5,1)],60).size==0


def test_gap_limit_and_coverage_use_native_frames(tmp_path):
    confidence=np.ones(100);confidence[40:53]=0
    t=track(tmp_path,np.full(100,440),confidence=confidence)
    assert not search_tracks([t],'1 A4')['results']
    result=search_tracks([t],'1 A4',{'max_gap':.13})
    assert result['results'][0]['coverage']==pytest.approx([.87])
    assert not search_tracks([t],'1 A4',{'max_gap':.13,'coverage':.9})['results']


def test_coarse_relaxation_never_becomes_formal_hit(tmp_path):
    t=track(tmp_path,np.full(100,440*2**(.8/12)))
    r=search_tracks([t],'.3 A4')
    assert r['candidates_seen']>0
    assert not r['results']


def test_overlap_dedup_and_truncation_reported(tmp_path):
    t=track(tmp_path,np.full(1000,440),[(0,10),(0,9),(1,10)])
    r=search_tracks([t],'.1 A4',candidate_limit=5)
    assert r['truncated']
    assert len({(x['asset_id'],x['start'],x['end']) for x in r['results']})==len(r['results'])


def test_vectorized_refine_matches_scalar_conditions():
    from ottosmasher.pitch_search import refine,refine_many
    rng=np.random.default_rng(410)
    data=np.column_stack((440*2**(rng.normal(0,.2,1000)/12),rng.uniform(.3,1,1000),rng.uniform(.001,.02,1000))).astype('float32')
    rows=parse('.2 A4\n.3 A4')
    starts=list(range(100))
    for extra in [{},{'coverage':.5,'max_gap':.1},{'coverage':.4,'stability_cents':65,'energy_min':.008,'energy_max':.018}]:
        opts=options(extra)
        scalar={i:r for i in starts if (r:=refine(data,i,rows,opts)) is not None}
        vector=dict(refine_many(data,starts,rows,opts))
        assert vector.keys()==scalar.keys()
        for i in scalar:
            assert vector[i]['score']==pytest.approx(scalar[i]['score'],abs=1e-5)
            assert vector[i]['coverage']==pytest.approx(scalar[i]['coverage'])


def test_sentence_boundary_filter_reports_unknown():
    from ottosmasher.pitch_scope import restrict_boundaries
    descriptor={'start':4,'root_knots':[[0,20],[2,22]]}
    result,unknown=restrict_boundaries([(4,6)],[{'start':20.5,'end':21.5}],descriptor,.5,{'start_tolerance':0})
    assert result==[(4.5,5.0)] and not unknown
    assert restrict_boundaries([(4,6)],[],descriptor,.5,{'end_tolerance':.1})==([],True)


def test_continuous_long_tone_is_one_hit_but_separate_events_survive(tmp_path):
    t=track(tmp_path,np.r_[np.full(1000,440),np.zeros(100),np.full(1000,440)])
    result=search_tracks([t],'.2 A4',candidate_limit=20)
    assert len(result['results'])==2
    assert result['results'][0]['start']<10
    assert result['results'][1]['start']>=10.8


def test_candidate_budget_gives_other_audio_an_opportunity(tmp_path):
    a=track(tmp_path/'a',np.full(10000,440));a['id']='a'
    b=track(tmp_path/'b',np.full(100,440));b['id']='b'
    result=search_tracks([a,b],'.2 A4',candidate_limit=2)
    assert {h['asset_id'] for h in result['results']}=={'a','b'}
