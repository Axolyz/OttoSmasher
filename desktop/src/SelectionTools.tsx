import React,{useEffect,useState} from 'react';
import {Alert,Button,Input,Modal,Space,Switch,Select,Checkbox} from 'antd';
import {request} from './Workspace';

export function DescendantRanges({id,timeline,origin=0,onSelect,sourceRange,role}:{id:string;timeline:any;origin?:number;sourceRange?:number[];role?:string;onSelect:(id:string)=>void}) {
  const [show,setShow]=useState(true),[error,setError]=useState('');
  const [depth,setDepth]=useState<number|undefined>(),[groups,setGroups]=useState<string[]>([]);
  const [layers,setLayers]=useState({phones:true,subtitles:true,tags:true});
  const [backend,setBackend]=useState('pydomino');
  const [extra,setExtra]=useState<any[]>([]);
  useEffect(()=>{if(!timeline)return;let cancelled=false;const controller=new AbortController();setError('');
    timeline.ottoSetDescendants([],onSelect);
    if(show)request('/api/samples/selection/resolve',{material_id:id,role,...(sourceRange?{clock:'source',start:sourceRange[0],end:sourceRange[1]}:{})},controller.signal)
      .then(selection=>request('/api/samples/selection/descendants',{selection,source:!!sourceRange,groups,max_depth:depth},controller.signal))
      .then(rows=>{if(!cancelled)timeline.ottoSetDescendants(rows,onSelect)}).catch(e=>{if(!controller.signal.aborted)setError(String(e))});
    return()=>{cancelled=true;controller.abort();timeline.ottoSetDescendants([],()=>{})};
  },[id,timeline,show,sourceRange?.[0],sourceRange?.[1],role,depth,groups.join(',')]);
  useEffect(()=>{if(!timeline)return;let timer:ReturnType<typeof setTimeout>;let controller:AbortController|undefined;let dead=false,serial=0;
    const load=()=>{const seq=++serial;clearTimeout(timer);controller?.abort();timer=setTimeout(async()=>{const pending=new AbortController();controller=pending;try{
      const [left,right]=timeline.ottoViewport();if(!(right>left))return;
      const lo=Math.max(0,left-.5),hi=Math.min(timeline.getDuration(),right+.5);
      const selection=await request('/api/samples/selection/resolve',{material_id:id,role,clock:sourceRange?'source':undefined,start:origin+lo,end:origin+hi},pending.signal);
      const data=await request('/api/samples/selection/timeline',{selection,backend},pending.signal);
      if(!dead&&seq===serial&&!pending.signal.aborted)setExtra([...(sourceRange?data.phones:[]),...data.annotations.filter((a:any)=>a.layer==='tags')].map(a=>({...a,start:a.start+lo,end:a.end+lo,effective_start:a.effective_start==null?undefined:a.effective_start+lo,effective_end:a.effective_end==null?undefined:a.effective_end+lo,viewport_offset:lo})));
    }catch(e){if(!dead&&seq===serial&&!pending.signal.aborted)setError(String(e))}},120)};
    const off=[timeline.on('ready',load),timeline.on('scroll',load),timeline.on('zoom',load)];window.addEventListener('otto:annotations-edited',load);load();
    return()=>{dead=true;window.removeEventListener('otto:annotations-edited',load);clearTimeout(timer);controller?.abort();off.forEach(f=>f());setExtra([])};
  },[id,timeline,role,backend,origin,!!sourceRange]);
  useEffect(()=>{timeline?.ottoSetLayers(extra,layers)},[timeline,extra,layers]);
  return <div style={{fontSize:12,padding:'2px 0'}}><Space size='small' wrap>
    <Switch size='small' checked={show} onChange={setShow}/><span>派生范围</span>
    <Select size='small' aria-label='派生层级' value={depth??-1} onChange={v=>setDepth(v<0?undefined:v)} style={{width:90}} options={[{value:-1,label:'全部层级'},{value:1,label:'直接派生'},{value:2,label:'两层以内'}]}/>
    <Select size='small' mode='tags' aria-label='派生轨道组' placeholder='轨道组' value={groups} onChange={setGroups} style={{minWidth:110}}/>
    {Object.entries(layers).map(([key,value])=><Checkbox key={key} checked={value} onChange={e=>setLayers({...layers,[key]:e.target.checked})}>{({phones:'音素',subtitles:'字幕',tags:'区段标签'} as any)[key]}</Checkbox>)}
    {sourceRange&&<Select size='small' aria-label='原片音素模型' value={backend} onChange={setBackend} options={['pydomino','narabas','phonetic'].map(value=>({value,label:value==='phonetic'?'HubertFA':value}))}/>}
  </Space>{error&&<small role='alert'>{error}</small>}</div>;
}

export function SelectionImport({id,range,role,clock,audioStream,open,onClose,onSaved}:{id:string;range:number[];role?:string;clock?:string;audioStream?:number;open:boolean;onClose:()=>void;onSaved:(id:string)=>void}) {
  const [selection,setSelection]=useState<any>(null),[importPreview,setImportPreview]=useState<any>(null);
  const [text,setText]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{let dead=false;if(open){setSelection(null);setImportPreview(null);setError('');setText(JSON.stringify({path:'',title:null,nature:'unclassified'},null,2));request('/api/samples/selection/resolve',{material_id:id,start:range[0],end:range[1],role,clock,audio_stream:audioStream}).then(x=>{if(!dead)setSelection(x)}).catch(e=>{if(!dead)setError(String(e))})}return()=>{dead=true}},[open]);
  useEffect(()=>{if(!open||!selection||!text)return;const path=JSON.parse(text).path;setImportPreview(null);if(!path)return;let dead=false;const timer=setTimeout(()=>request('/api/samples/selection/external-import-preview',{selection,path}).then(p=>{if(!dead){setImportPreview(p);setError('')}}).catch(e=>{if(!dead)setError(String(e))}),200);return()=>{dead=true;clearTimeout(timer)}},[open,selection,text]);
  async function save(){setBusy(true);setError('');try{if(!selection||!importPreview)throw Error('请先选择有效音频文件');
    const child=await request('/api/samples/selection/external-import',{...JSON.parse(text),selection});onSaved(child.id);onClose();}catch(e){setError(String(e));}finally{setBusy(false);}}
  return <Modal title='从选区起点回导成品' open={open} onCancel={onClose} footer={<Space><Button onClick={onClose}>取消</Button><Button disabled={!importPreview} loading={busy} type='primary' onClick={save}>保存子采样</Button></Space>}>
    <p>{clock==='source'?'原片时间':'本地时间'} 起点 {range[0].toFixed(3)} 秒。终点由导入文件时长计算，忽略手选终点；超出当前资产边界时不保存。成品按原时间轴连续映射，不推断内部剪辑或变速。</p>
    {importPreview&&<p>文件时长 {importPreview.duration.toFixed(3)} 秒 · 回导终点 {(clock==='source'?importPreview.root_knots.at(-1)[1]:range[0]+importPreview.duration).toFixed(3)} 秒</p>}
    {error&&<Alert type='error' message={error}/>}{text&&<Space orientation='vertical' style={{width:'100%'}}><Space.Compact style={{width:'100%'}}><Input aria-label='回导文件' placeholder='成品音频文件' value={JSON.parse(text).path} onChange={e=>setText(JSON.stringify({...JSON.parse(text),path:e.target.value}))}/><Button onClick={async()=>{const paths=await window.ottoDesktop?.pick();if(paths?.[0])setText(JSON.stringify({...JSON.parse(text),path:paths[0]}))}}>选择文件</Button></Space.Compact><Input aria-label='回导采样名称' placeholder='自动命名（可修改）' value={JSON.parse(text).title||''} onChange={e=>setText(JSON.stringify({...JSON.parse(text),title:e.target.value||null}))}/><Select aria-label='回导性质' value={JSON.parse(text).nature} onChange={nature=>setText(JSON.stringify({...JSON.parse(text),nature}))} options={['speech','pitched','unpitched','unclassified'].map(value=>({value,label:({speech:'语音',pitched:'有音高',unpitched:'无音高',unclassified:'未分类'} as any)[value]}))}/></Space>}
  </Modal>;
}
