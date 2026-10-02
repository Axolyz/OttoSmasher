import {DraftNumber as InputNumber} from "./DraftNumber";
import React,{useEffect,useState} from 'react';
import {Alert,App,Button,Input,Space,Select,Collapse} from 'antd';
import {request} from './Workspace';
export default function PitchSearch({scope,onResults}:{scope:any;onResults:(r:any,q:any)=>void}){
  const {message}=App.useApp();const [text,setText]=useState('0.40 A4\n0.30 C5..D5'),[advanced,setAdvanced]=useState('{}'),[mode,setMode]=useState('samples');
  const [tolerance,setTolerance]=useState(50),[coverageMin,setCoverageMin]=useState(.8),[gap,setGap]=useState(.12);
  const [rows,setRows]=useState<any[]>([]),[coverage,setCoverage]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  function body(){const extra=JSON.parse(advanced);return {...extra,text,mode,scope:{...(mode==='sources'?{text:scope.text,tag_expression:scope.tag_expression,source_id:scope.source_id,intersections:scope.intersections}:scope),...(extra.scope||{})},parameters:{tolerance_cents:tolerance,coverage:coverageMin,max_gap:gap,...extra.parameters}}}
  const queryKey=JSON.stringify({scope,mode,text,advanced,tolerance,coverageMin,gap});
  useEffect(()=>{const controller=new AbortController();const timer=setTimeout(()=>{
    try{void request('/api/samples/pitch-query/coverage',body(),controller.signal).then(setCoverage).catch(e=>{if(!controller.signal.aborted)setError(String(e))});void request('/api/samples/pitch-query/parse',{text},controller.signal).then(x=>setRows(x.rows)).catch(()=>setRows([]))}catch(e){setError(String(e))}
  },250);return()=>{clearTimeout(timer);controller.abort()}},[queryKey]);
  async function search(){setBusy(true);setError('');try{const began=performance.now();const q=body();const r=await request('/api/samples/pitch-query',q);setCoverage(r.coverage);onResults({...r,results:r.grouped_results,grouped_results:undefined,_ui_started_at:began},q)}catch(e){setError(String(e))}finally{setBusy(false)}}
  async function prepare(){try{const j=await request('/api/samples/pitch-index',body());message.info('音高索引任务已排队：'+j.id)}catch(e){setError(String(e))}}
  useEffect(()=>{const update=(e:Event)=>{if((e as CustomEvent).detail?.some((j:any)=>j.operation==='pitch-index'&&j.status==='succeeded')){try{void request('/api/samples/pitch-query/coverage',body()).then(setCoverage).catch(()=>{})}catch{}}};window.addEventListener('otto:jobs-updated',update);return()=>window.removeEventListener('otto:jobs-updated',update)},[queryKey]);
  const indexed=coverage?.[mode==='sources'?'indexed_assets':'indexed_samples'],eligible=coverage?.[mode==='sources'?'eligible_assets':'eligible_samples'];
  const total=rows.reduce((sum,r)=>sum+r.duration,0)||1,low=Math.min(...rows.map(r=>r.low),60)-2,high=Math.max(...rows.map(r=>r.high),72)+2;let offset=0;
  return <div className='pitch-query'><Space align='start' wrap>
    <Input.TextArea aria-label='音高查询文本' rows={3} value={text} onChange={e=>setText(e.target.value)} style={{width:240,fontFamily:'monospace'}} placeholder='0.40 A4' />
    <Space orientation='vertical'><Select value={mode} onChange={setMode} options={[{value:'samples',label:'已保存采样'},{value:'sources',label:'已分析原片音轨'}]}/><Button type='primary' loading={busy} disabled={indexed===0} onClick={search}>搜索音高</Button></Space>
    <Space orientation='vertical'><span>容差 <InputNumber aria-label='音高容差 cents' min={0} value={tolerance} onChange={(v:any)=>setTolerance(v??50)}/> cents</span><span>有效覆盖 <InputNumber aria-label='音高有效覆盖率' min={0} max={1} step={.05} value={coverageMin} onChange={(v:any)=>setCoverageMin(v??.8)}/></span><span>最长缺口 <InputNumber aria-label='最长音高缺口' min={0} step={.01} value={gap} onChange={(v:any)=>setGap(v??.12)}/> 秒</span></Space>
  </Space>
    <small>每行：持续秒数 音符或范围（如 0.30 C5..D5）</small>
    {rows.length>0&&<svg aria-label='音高区间预览' viewBox='0 0 800 60' style={{width:'100%',height:60}}>{rows.map((r,i)=>{const x=offset/total*780+10;offset+=r.duration;return <g key={i}><rect x={x} y={40-(r.high-low)/(high-low)*30} width={r.duration/total*780} height={Math.max(2,(r.high-r.low)/(high-low)*30)} fill='#69b1ff'/><text x={x} y='58' fill='#aaa' fontSize='11'>{r.duration.toFixed(2)}s</text></g>})}</svg>}
    {error&&<Alert type='error' message={error}/>}
    <Space><small>{coverage?`${indexed}/${eligible} 已索引${indexed===0?' · 尚未准备音高索引':indexed<eligible?' · 仅搜索已有有效索引':''}`:'正在检查索引覆盖…'}</small><Button size='small' onClick={prepare}>准备当前范围索引</Button></Space>
    <Collapse ghost size='small' items={[{key:'advanced',label:'高级参数',children:<Input.TextArea aria-label='音高高级参数 JSON' value={advanced} onChange={e=>setAdvanced(e.target.value)}/>}]}/>
  </div>;
}
