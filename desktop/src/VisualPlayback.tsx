import React,{useEffect,useRef,useState} from 'react';
import {Alert} from 'antd';
import {VideoPlayer} from './NativePlayer';
import {request} from './Workspace';

export default function VisualPlayback({id,master,revision,role,timeOffset=0}:{id:string;master:HTMLMediaElement|null;revision?:number;role?:string;timeOffset?:number}) {
  const [binding,setBinding]=useState<any>(null),[error,setError]=useState('');
  const video=useRef<HTMLVideoElement>(null);
  useEffect(()=>{let dead=false;setBinding(null);setError('');request(`/api/samples/${id}/visual?native=${!!window.ottoDesktop?.player}&role=${encodeURIComponent(role||"selected")}`)
    .then(b=>{if(!dead)setBinding(b);}).catch(e=>{if(!dead)setError(String(e));});return()=>{dead=true};},[id,revision,role]);
  useEffect(()=>{
    if(!master||!binding||binding.mode==='image')return;
    let frame=0,dead=false;
    function position(time:number){
      if(binding.mode==='local_loop')return {time:time%binding.duration,rate:1};
      const knots=binding.root_knots as number[][];
      let i=0;while(i<knots.length-2&&knots[i+1][0]<time)i++;
      const a=knots[i],b=knots[i+1],bounded=Math.max(a[0],Math.min(b[0],time));
      const rate=(b[1]-a[1])/(b[0]-a[0]);
      return {time:a[1]+(bounded-a[0])*rate-binding.video_origin,rate};
    }
    function sync(force=false){const v=video.current;if(!v)return;
      const p=position(master!.currentTime+timeOffset);v.muted=true;
      if(force||Math.abs(v.currentTime-p.time)>.08)v.currentTime=p.time;
      const rate=master!.playbackRate*p.rate;
      if(rate>=.25&&rate<=4)v.playbackRate=rate;
      else {v.pause();v.currentTime=p.time;return;}
      if(master!.paused)v.pause();
      else if(v.paused)void v.play().catch(e=>{if(!dead)setError(String(e))});
    }
    const force=()=>sync(true),tick=()=>{if(!master!.paused)sync();frame=requestAnimationFrame(tick)};
    const events=['play','pause','seeking','seeked','ratechange','ended'];events.forEach(e=>master.addEventListener(e,force));
    video.current?.addEventListener('loadedmetadata',force);force();frame=requestAnimationFrame(tick);
    return()=>{dead=true;cancelAnimationFrame(frame);events.forEach(e=>master.removeEventListener(e,force));video.current?.removeEventListener('loadedmetadata',force);video.current?.pause();};
  },[master,binding,timeOffset]);
  if(error)return <Alert type='warning' message={'画面：'+error}/>;
  if(!binding)return null;
  return <div className='bound-visual' style={{maxHeight:'min(260px, 22vh)',overflow:'hidden',background:'#101010',textAlign:'center'}}>
    {binding.mode==='image'?<img src={binding.url} alt='绑定画面' style={{maxWidth:'100%',maxHeight:'min(260px, 22vh)',objectFit:'contain'}}/>:
      <VideoPlayer ref={video} src={binding.url} muted slave controls={false} preload='auto' style={{width:'100%',height:'min(250px, 22vh)',objectFit:'contain'}}
        onLoadedMetadata={()=>{if(video.current&&!master&&binding.mode==='sync')video.current.currentTime=(binding.root_knots?.[0]?.[1]||0)-binding.video_origin}}
        onClick={()=>{if(master){if(master.paused)void master.play();else master.pause();}}} onError={()=>setError('画面解码失败')}/>}
  </div>;
}
