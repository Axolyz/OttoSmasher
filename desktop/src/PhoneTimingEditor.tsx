import {audioTimeline} from "./AudioTimeline";
import React, {useEffect, useRef, useState} from "react";
import {Alert, App, Button, Input, Modal, Select, Space, Collapse} from "antd";
import {request} from "./Workspace";
export default function PhoneTimingEditor({target,onClose,onSaved}: {target:{id:string;backend:string}|null;onClose:()=>void;onSaved:()=>void}) {
  const {message}=App.useApp(); const [doc,setDoc]=useState<any>(null); const [error,setError]=useState("");
  const [busy,setBusy]=useState(false); const [history,setHistory]=useState<any>({versions:[],revision:0});
  const host=useRef<HTMLDivElement>(null), wave=useRef<any>(null), descriptor=useRef<any>(null);
  const documentRef=useRef(doc);documentRef.current=doc;
  const drag=useRef<{index:number;side:number}|null>(null);
  const phones=(doc?.text||'').split('\n').filter((x:string)=>x.trim()).map((x:string)=>x.trim().split(/\s+/));
  const valid=phones.length>0&&phones.every((p:string[])=>p.length===3&&Number.isFinite(+p[0])&&Number.isFinite(+p[1]));
  function move(e:React.PointerEvent<SVGSVGElement>){if(!drag.current||!valid)return;
    const {index,side}=drag.current,rect=e.currentTarget.getBoundingClientRect();
    const time=doc.range[0]+Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width))*(doc.range[1]-doc.range[0]);
    const lower=side===0?(index?+phones[index-1][1]:doc.range[0]):+phones[index][0]+.000001;
    const upper=side===1?(index+1<phones.length?+phones[index+1][0]:doc.range[1]):+phones[index][1]-.000001;
    const updated=phones.map((p:string[])=>[...p]);updated[index][side]=Math.max(lower,Math.min(upper,time)).toFixed(9);
    setDoc({...doc,text:updated.map((p:string[])=>p.join('\t')).join('\n')});
  }
  useEffect(()=>{if(!target)return;let dead=false;const controller=new AbortController();
    Promise.all([request('/api/samples/'+target.id),request('/api/samples/'+target.id+'/waveform?role=selected',undefined,controller.signal),request('/api/samples/'+target.id+'/audition',{role:'selected',native:!!window.ottoDesktop?.player},controller.signal)])
    .then(([sample,peaks,playback])=>{if(dead||!host.current)return;descriptor.current=sample;
      const w=audioTimeline({container:host.current,peaks:peaks.peaks,peakLevels:peaks.peak_levels,duration:peaks.duration,url:playback.url,height:120});wave.current=w;
      (w as any).ottoSetAnnotationEditor((id:string,start:number,end:number)=>{
        const d=documentRef.current;if(!d)return;const index=+id.replace('phone-',''),lines=d.text.split('\n').map((s:string)=>s.split(/\s+/));
        const knots=sample.audio_asset.root_knots;
        const convert=(t:number)=>{if(d.clock==='asset')return sample.asset_selection.start+t;let i=0;while(i<knots.length-2&&knots[i+1][0]<t)i++;const a=knots[i],b=knots[i+1];return a[1]+(t-a[0])*(b[1]-a[1])/(b[0]-a[0])};
        lines[index][0]=convert(start).toFixed(9);lines[index][1]=convert(end).toFixed(9);setDoc({...d,text:lines.map((p:string[])=>p.join('\t')).join('\n')});
      });w.on('ready',()=>paint());
    }).catch(e=>{if(!controller.signal.aborted)setError(String(e))});
    return()=>{dead=true;controller.abort();wave.current?.destroy();wave.current=null};
  },[target?.id]);
  function paint(){const d=documentRef.current,sample=descriptor.current;if(!d||!sample||!wave.current)return;const knots=sample.audio_asset.root_knots;
    const convert=(t:number)=>{if(d.clock==='asset')return t-sample.asset_selection.start;let i=0;while(i<knots.length-2&&knots[i+1][1]<t)i++;const a=knots[i],b=knots[i+1];return a[0]+(t-a[1])*(b[0]-a[0])/(b[1]-a[1])};
    wave.current.ottoSetAnnotations(d.text.split('\n').filter(Boolean).map((line:string,i:number)=>{const p=line.trim().split(/\s+/);return {id:'phone-'+i,start:convert(+p[0]),end:convert(+p[1]),label:p[2]}}).filter((p:any)=>p.start>=0&&p.end<=wave.current.getDuration()));
  }
  useEffect(paint,[doc]);
  async function load() {
    if(!target)return;
    const body={material_id:target.id,backend:target.backend};
    const [d,h]=await Promise.all([request("/api/samples/phone-times/export",body),request("/api/samples/phone-times/versions",body)]);
    setDoc(d);setHistory(h);
  }
  useEffect(()=>{setDoc(null);setError("");if(target)void load().catch(e=>setError(String(e)));},[target]);
  async function save(){setBusy(true);setError("");try{await request("/api/samples/phone-times/apply",doc);await load();onSaved();message.success("人工时间版本已保存，重新 FA 不会覆盖");}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function choose(id:string){if(!target)return;setBusy(true);try{const r=await request("/api/samples/phone-times/choose",{material_id:target.id,backend:target.backend,run_id:id,base_revision:history.revision});if(!r.adopted)throw Error("当前版本已变化，请重新载入");await load();onSaved();}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <Modal open={target!==null} title="音素时间戳 · 仅修改时间" width={780} onCancel={onClose} footer={<Space><Button onClick={onClose}>关闭</Button><Button type="primary" disabled={!doc} loading={busy} onClick={save}>保存人工版本</Button></Space>}>
    {error&&<Alert type="error" message={error}/>}
    <div ref={host} aria-label="音素边界编辑波形"/>
    {doc&&<><p>坐标：{doc.clock==='asset'?'声音资产局部时间':'原片时间'}；范围 [{doc.range[0]}, {doc.range[1]}) 秒。每行：开始秒、结束秒、原音素。不能增删或重排。</p>
      <Select style={{width:'100%',marginBottom:12}} placeholder="切换保存的版本" value={history.versions.find((v:any)=>v.active)?.id}
        options={history.versions.map((v:any)=>({value:v.id,label:`${v.human?'人工时间':'模型结果'} · ${new Date(v.created*1000).toLocaleString()}`}))} onChange={choose}/>
      <Collapse items={[{key:"text",label:"精确时间文本",children:<Input.TextArea aria-label="音素时间文本" rows={17} spellCheck={false} style={{fontFamily:'monospace'}} value={doc.text} onChange={e=>setDoc({...doc,text:e.target.value})}/>}]} /></>}
  </Modal>;
}
