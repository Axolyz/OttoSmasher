import React,{useEffect,useState} from 'react';
import {Alert,Form,Select} from 'antd';
import {request} from './Workspace';
export default function SeparationControls({text,onChange}:{text:string;onChange:(s:string)=>void}) {
  const [models,setModels]=useState<any[]>([]),[error,setError]=useState('');
  const p=JSON.parse(text),chosen=models.find(m=>m.name===p.model);
  useEffect(()=>{let dead=false;request('/api/helper/studio').then(s=>{if(!dead){setModels(s.available_models||[]);setError(s.error||'')}}).catch(e=>{if(!dead)setError(String(e))});return()=>{dead=true}},[]);
  return <Form layout='vertical'>{error&&<Alert type='warning' message={error}/>}<Form.Item label='Studio 已下载模型'><Select allowClear placeholder='使用设置中的默认模型' value={p.model||undefined} options={models.map(m=>({value:m.name,label:m.name}))} onChange={model=>onChange(JSON.stringify({...p,model:model||null,stems:null}))}/></Form.Item><Form.Item label='保留声部'><Select mode='multiple' placeholder='保留全部实际声部' value={p.stems||[]} options={(chosen?.stems||[]).map((value:string)=>({value,label:value}))} onChange={stems=>onChange(JSON.stringify({...p,stems:stems.length?stems:null}))}/></Form.Item></Form>;
}
