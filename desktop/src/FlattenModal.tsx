import React,{useEffect,useRef,useState} from 'react';
import {Alert,Input,Modal,Select,Space} from 'antd';
import {DraftNumber} from './DraftNumber';
import {request} from './Workspace';
import {audioTimeline} from './AudioTimeline';

export default function FlattenModal({input,onClose,onQueued,initialMode='all'}:{input:any;onClose:()=>void;onQueued:(id:string)=>void;initialMode?:string}) {
  const [frozen]=useState(input);
  const [context,setContext]=useState<any>(null),[timeline,setTimeline]=useState<any>(null);
  const [mode,setMode]=useState(initialMode),[strategy,setStrategy]=useState(initialMode==='all'?'region':'boundary');
  const [side,setSide]=useState('left'),[target,setTarget]=useState(''),[title,setTitle]=useState('');
  const [inner,setInner]=useState([0,0]),[transition,setTransition]=useState([.05,.05]);
  const [preview,setPreview]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false);
  const wrap=useRef<HTMLDivElement>(null);
  useEffect(()=>{let dead=false;request('/api/samples/selection/flatten-context',frozen).then(c=>{if(dead)return;setContext(c);setInner([Math.min(.1,c.duration/4),Math.max(c.duration-.1,c.duration*.75)]);}).catch(e=>{if(!dead)setError(String(e))}).finally(()=>{if(!dead)setLoading(false)});return()=>{dead=true}},[]);
  useEffect(()=>{if(!context||!wrap.current)return;const w:any=audioTimeline({container:wrap.current,url:context.url,peaks:context.peaks,duration:context.duration,height:100});setTimeline(w);return()=>{w.pause();w.destroy();setTimeline(null)}},[context]);
  useEffect(()=>{if(!timeline||!context)return;if(mode==='interior')timeline.ottoSetInterior(inner,[0,context.duration],(a:number,b:number)=>setInner([a,b]),transition);else timeline.ottoSetInterior(null);return()=>timeline.ottoSetInterior(null)},[timeline,context,mode,JSON.stringify(inner),JSON.stringify(transition)]);
  const parameters={mode,pitch_strategy:strategy,boundary_side:side,target:strategy==='manual'?(target.trim()?(/^\d+(\.\d+)?$/.test(target.trim())?Number(target):target.trim()):null):null,inner:mode==='interior'?inner:null,transition};
  useEffect(()=>{if(!context)return;let dead=false;setPreview(null);setLoading(true);const timer=setTimeout(()=>{request('/api/samples/selection/flatten-preview',{selection:context.selection,material_id:frozen.material_id,backend:frozen.backend,...parameters}).then(p=>{if(dead)return;setPreview(p);setError('');timeline?.ottoSetFrames(p.frames)}).catch(e=>{if(!dead)setError(String(e))}).finally(()=>{if(!dead)setLoading(false)})},180);return()=>{dead=true;clearTimeout(timer)}},[context,timeline,JSON.stringify(parameters)]);
  async function submit(){setBusy(true);try{const job=await request('/api/samples/selection/flatten',{selection:context.selection,material_id:frozen.material_id,backend:frozen.backend,expected_asset:context.asset,...parameters,title:title.trim()||null});onQueued(job.id);onClose()}catch(e){setError(String(e))}finally{setBusy(false)}}
  return <Modal open title="拉平" width={800} styles={{body:{maxHeight:'calc(100vh - 240px)',overflowY:'auto'}}} onCancel={onClose} okText="开始拉平" cancelText="取消" onOk={submit} confirmLoading={busy} okButtonProps={{disabled:loading||!context||!preview||!!error}}>
    <p>音源：{({raw:'原混音',vocals:'人声',original:'原混音',effects:'音效',flattened:'拉平成品'} as any)[context?.asset.role]||context?.asset.role||frozen.role||'采样绑定的音源'} · 外选区 [{Number(frozen.start||0).toFixed(3)}, {Number(frozen.end||0).toFixed(3)}) 秒（已固定）</p>
    <div ref={wrap}/>
    <Space orientation="vertical" style={{width:'100%',marginTop:12}}>
      <Space wrap><span>处理范围</span><Select aria-label="拉平模式" value={mode} style={{width:230}} onChange={v=>{setMode(v);setStrategy(v==='all'?'region':'boundary')}} options={[{value:'all',label:'整段拉平'},{value:'from_first_vowel',label:'从首个元音起拉平'},{value:'interior',label:'内部拉平，首尾保留'}]}/></Space>
      {mode==='from_first_vowel'&&<small>包含拨音 N；起点之后到选区末尾全部统一音高，包括有声辅音，无声不补音。</small>}
      {mode==='interior'&&<><small>拖动上方金色内边界。时间相对于外选区起点；定高平台至少 30 ms。</small><Space wrap><span>内部范围（秒）</span>{inner.map((v,i)=><DraftNumber key={i} aria-label={i?'内部结束秒':'内部开始秒'} value={v} min={0} max={context?.duration} step={.01} precision={3} onChange={(n:any)=>{setError('');setInner(x=>x.map((p,j)=>j===i?n:p))}}/>)}<span>左右过渡（秒）</span>{transition.map((v,i)=><DraftNumber key={i} aria-label={i?'右过渡秒':'左过渡秒'} value={v} min={0} step={.01} precision={3} onChange={(n:any)=>{setError('');setTransition(x=>x.map((p,j)=>j===i?n:p))}}/>)}</Space></>}
      <Space wrap><span>目标音高</span><Select aria-label="定音方式" value={strategy} style={{width:180}} onChange={setStrategy} options={[{value:'region',label:'段内自动定音'},{value:'boundary',label:'交界自动定音'},{value:'manual',label:'手动指定'}]}/>
        {strategy==='boundary'&&<Select aria-label="交界参考侧" value={side} onChange={setSide} options={[{value:'left',label:'左侧（起点）'},{value:'right',label:'右侧（终点）'}]}/>}
        {strategy==='manual'&&<Input aria-label="拉平目标音高" placeholder="如 A4 或 440（Hz）" value={target} onChange={e=>setTarget(e.target.value)}/>}
      </Space>
      {strategy==='boundary'&&<small>参考所选边界向内 100 ms 的可靠音高，吸附最近半音；不足时不自动换侧。</small>}
      {preview&&<div>{preview.note?`缓存预估：${preview.note.name}${preview.reference?` · 参考 ${preview.reference.map((n:number)=>n.toFixed(3)).join('–')} 秒`:''}`:'任务中分析确定'}。执行时以实际输入测量为准。</div>}
      <Input aria-label="拉平成品名称" placeholder="自动命名（可修改）" value={title} onChange={e=>setTitle(e.target.value)}/>
      {error&&<Alert type="error" title={error}/>}
    </Space>
  </Modal>;
}
