import React, { useEffect, useState } from "react";
import { Alert, Button, Collapse, Select, Space, Tag } from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";
import { NativeAudio } from "./NativePlayer";

const base = "/api/samples/";
async function call(url: string, body?: any) {
  const r = await fetch(url, body === undefined ? undefined : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const data = await r.json(); if (!r.ok) throw Error(data.detail || r.statusText); return data;
}
export function NativeAlignment({id, locate, task, report}: {id:string;locate:(a:number,b:number,role:string)=>void;task:(t:any)=>void;report:(e:any)=>void}) {
  const [open,setOpen]=useState(false),[data,setData]=useState<any>(null),[model,setModel]=useState("yohane"),[url,setUrl]=useState("");
  useEffect(()=>{setData(null);setUrl("");},[id]);
  useEffect(()=>{
    if(!open) return;
    let dead=false;
    const load=()=>call(base+id+"/native-alignment").then(d=>{if(!dead)setData(d);}).catch(report);
    void load(); const tick=setInterval(load,5000);
    return ()=>{dead=true;clearInterval(tick);};
  },[id,open]);
  const result=data?.results.find((r:any)=>r.model===model);
  const play=async(i:number)=>{try{const p=await call(base+id+"/native-alignment/play",{model,index:i,native:!!window.ottoDesktop?.player});setUrl(p.url);}catch(e){report(e);}};
  return <Collapse onChange={k=>setOpen(k.length>0)} items={[{key:"native",label:"字符／音节时间层",children:<>
    <Space wrap><Select value={model} onChange={m=>{setModel(m);setUrl("");}} options={(data?.models||[]).map((m:any)=>({value:m.id,label:m.name,disabled:!m.available}))} style={{minWidth:220}} />
    <Button disabled={!data?.models.find((m:any)=>m.id===model)?.available} onClick={()=>call(base+id+"/native-alignment",{model}).then(task).catch(report)}>分析此台词</Button></Space>
    <p><small>独立时间层；不参与音素计数或节奏检索。使用完整人声音轨上的台词范围。</small></p>
    {result?.status==="failed"&&<Alert type="error" title={result.error}/>}
    {result?.stale&&<Alert type="warning" title="音源、模型或处理流程已改变，请重新分析"/>}
    {result?.warnings?.map((w:string)=><Alert key={w} type="warning" title={w}/>)}
    {result?.status==="ready"&&<><Tag>{result.granularity==="syllable"?"音节":result.granularity==="word"?"词":"字符／词"}</Tag><Tag>{result.device}</Tag>
    <Space wrap>{result.segments.map((s:any,i:number)=><Space.Compact key={i}>
      <Button size="small" disabled={result.stale || s.end <= s.start} title={`${s.start.toFixed(3)}–${s.end.toFixed(3)} 秒`} onClick={()=>locate(s.start,s.end,result.input.asset.role)}>{s.text}</Button>
      <Button size="small" disabled={result.stale || s.end <= s.start} aria-label={`试听 ${s.text}`} icon={<PlayCircleOutlined/>} onClick={()=>void play(i)}/>
    </Space.Compact>)}</Space></>}
    {url&&<NativeAudio key={url} src={url} controls autoPlay/>}
  </>}]} />;
}
