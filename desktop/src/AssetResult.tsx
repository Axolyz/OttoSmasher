import React,{useState} from 'react';
import {Alert,Button,Input,Space} from 'antd';
import {request} from './Workspace';

/** Unsaved outputs stay assets until this explicit save. */
export default function AssetResult({selection,name,onSaved}:{selection:any;name?:string;onSaved?:(id:string)=>void}) {
  const [text,setText]=useState(JSON.stringify({title:name||null,tags:[]},null,2));
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState('');
  async function play(){try{const r=await request('/api/samples/selection/preview',{selection});window.dispatchEvent(new CustomEvent('otto:pitch-audition',{detail:r.url}));}catch(e){setError(String(e));}}
  async function save(){setBusy(true);setError('');try{const r=await request('/api/samples/selection/save',{...JSON.parse(text),selection});setSaved(r.id);onSaved?.(r.id);}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <div style={{marginBottom:16}}><p>{name||'选区'} · 资产时间 [{selection.start.toFixed(3)}, {selection.end.toFixed(3)})</p>
    {error&&<Alert type='error' message={error}/>}{saved&&<Alert type='success' message='已保存采样'/>}
    <Input.TextArea rows={4} aria-label='保存资产采样参数' value={text} onChange={e=>setText(e.target.value)}/>
    <Space><Button onClick={play}>试听资产</Button><Button type='primary' loading={busy} disabled={!!saved} onClick={save}>保存为采样</Button></Space></div>;
}
