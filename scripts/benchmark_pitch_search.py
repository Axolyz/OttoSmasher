"""Synthetic 100k selections / 50h independent F0 benchmark, not audio QA.

Use --prepare once; each --query invocation measures a fresh Python process.
"""
import argparse,json,time,threading,resource,sys
from pathlib import Path
import numpy as np
from ottosmasher.pitch_search import write_index,search_tracks

p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True);p.add_argument('--prepare',action='store_true');p.add_argument('--query',choices=['single','multi','none','common','overlap'],default='single');p.add_argument('--repeat',type=int,default=5);args=p.parse_args()
if args.prepare:
    rng=np.random.default_rng(20261001);args.directory.mkdir(parents=True,exist_ok=True);tracks=[]
    for i in range(50):
        folder=args.directory/f'{i:03}'
        # Every track has different continuous values; no repeated file aliases.
        pitch=np.repeat(rng.choice([60,64,67,69,72],3600),100)+rng.normal(0,.04,360000)
        # Include known positive multi-segment matches at differing phases.
        for at in range(1000+i,359900,10000):
            pitch[at:at+90]=np.repeat([60,64,67],30)+rng.normal(0,.02,90)
        f0=440*2**((pitch-69)/12);confidence=rng.uniform(.65,1,360000);energy=rng.uniform(.005,.02,360000)
        write_index(folder,f0,confidence,energy)
        start=rng.uniform(0,3595,2000);ranges=[(float(s),float(s+5)) for s in start]
        tracks.append({'id':f'track-{i}','path':str(folder),'frames':360000,'ranges':ranges})
    (args.directory/'tracks.json').write_text(json.dumps(tracks))
    print(json.dumps({'samples':100000,'unique_f0_hours':50,'native_frames':18000000,'synthetic':True}));sys.exit()
tracks=json.loads((args.directory/'tracks.json').read_text())
queries={'single':'.4 A4','multi':'.3 C4\n.3 E4\n.3 G4','none':'1 C1','common':'.1 C4..C5','overlap':'.5 C4'}
if args.query=='overlap':
    for t in tracks:t['ranges']=[(0,3599)]*2000
try:
    import psutil
    process=psutil.Process();baseline=process.memory_info().rss;peaks=[baseline];done=threading.Event()
    def sample():
        while not done.wait(.005):peaks.append(process.memory_info().rss)
    thread=threading.Thread(target=sample,daemon=True);thread.start()
except ImportError:
    baseline=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;peaks=[baseline];done=None
elapsed=[];result=None
for _ in range(args.repeat):
    t=time.perf_counter();result=search_tracks(tracks,queries[args.query]);elapsed.append(time.perf_counter()-t)
if done:done.set();thread.join();delta=max(peaks)-baseline
else:
    scale=1 if sys.platform=='darwin' else 1024
    delta=(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss-baseline)*scale
print(json.dumps({'case':args.query,'synthetic':True,'samples':100000,'unique_f0_hours':50,'cold_query_seconds':elapsed[0],
    'warm_p95_seconds':float(np.percentile(elapsed[1:],95)) if len(elapsed)>1 else None,
    'query_peak_extra_mib':delta/2**20,'times':elapsed,'matches':len(result['results']),'candidates_seen':result['candidates_seen'],'truncated':result['truncated']},indent=2))
