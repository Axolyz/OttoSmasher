import React,{useEffect,useState} from 'react';
import {Alert,Button,Input,Modal,Space,Select,Collapse} from 'antd';
import {request} from './Workspace';
import BusinessTextEditor from './BusinessTextEditor';
export default function SelectionEditor({selection,sampleId,open,onClose,onSaved}:{selection:any;sampleId?:string;open:boolean;onClose:()=>void;onSaved:()=>void}) {
  const [objects,setObjects]=useState<any[]|null>(null),[draft,setDraft]=useState<any>(null),[rows,setRows]=useState<any[]>([]);
  const [error,setError]=useState(''),[fa,setFa]=useState('{}'),[busy,setBusy]=useState(false);
  useEffect(()=>{setError('');setRows([]);if(open&&selection)request('/api/samples/selection/annotations',{selection}).then(r=>{setRows(r);setFa(JSON.stringify({annotation_id:r.find((x:any)=>x.kind==='dialogue')?.id||'',backend:null},null,2));}).catch(e=>setError(String(e)));},[open,selection]);
  async function create(){try{setDraft(await request('/api/samples/selection/new-annotation',{selection}));}catch(e){setError(String(e));}}
  async function runFA(){setBusy(true);setError('');try{const result=await request('/api/samples/selection/reanalyse',{...JSON.parse(fa),selection});setError('FA 已排队：'+result.job.id+'；实际资产输入区间 '+JSON.stringify(result.inputs[0].input_range)+'，前后容差 '+JSON.stringify(result.inputs[0].padding_actual));}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <><Modal title='选区文字、区段标签与轨道组' open={open} onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
    <p>资产局部区间 [{selection?.start}, {selection?.end})。区段文档会标明 source/group/asset 范围；新建默认用来源坐标，保存前可修改。</p>
    {error&&<Alert message={error} type={error.startsWith('FA 已')?'info':'error'}/>}
    <Space wrap>{sampleId&&<Button onClick={()=>request('/api/samples/edit/promote-tags',{sample_id:sampleId}).then(setDraft).catch(e=>setError(String(e)))}>提升本地标签为区段</Button>}<Button onClick={create}>新增区段标注</Button><Button disabled={!rows.length} onClick={()=>setObjects(rows.map(r=>({type:'annotation',id:r.id})))}>编辑交叠标注</Button>
      <Button disabled={!rows.some(r=>r.kind==='dialogue')} onClick={()=>setObjects(rows.filter(r=>r.kind==='dialogue').map(r=>({type:'alignment_text',id:r.id})))}>编辑对齐文本</Button><Collapse ghost size='small' items={[{key:'groups',label:'高级：任意轨道组',children:<Button onClick={()=>setObjects([{type:'track_group',id:selection.asset_id}])}>编辑轨道分组</Button>}]}/></Space>
    <p>从当前声音选区重新 FA：选择文字和模型。无需先保存采样。</p>
    <Space><Select aria-label='对齐文字区段' style={{width:260}} value={JSON.parse(fa).annotation_id} onChange={annotation_id=>setFa(JSON.stringify({...JSON.parse(fa),annotation_id}))} options={rows.filter(r=>r.kind==='dialogue').map(r=>({value:r.id,label:r.text||'无文字'}))}/><Select aria-label='FA 模型' value={JSON.parse(fa).backend||'default'} onChange={backend=>setFa(JSON.stringify({...JSON.parse(fa),backend:backend==='default'?null:backend}))} options={['default','pydomino','narabas','phonetic'].map(value=>({value,label:value==='default'?'默认模型':value==='phonetic'?'HubertFA':value}))}/></Space><Button loading={busy} onClick={runFA}>重新 FA 当前选区</Button>
    <small>交叠标注：{rows.map(r=>`${r.id} ${r.text||r.tags.join(' ')}`).join(' / ')||'无'}</small>
  </Modal><BusinessTextEditor objects={objects} draft={draft} onClose={()=>{setObjects(null);setDraft(null)}} onSaved={()=>{onSaved();request('/api/samples/selection/annotations',{selection}).then(setRows).catch(e=>setError(String(e)));}}/></>;
}
