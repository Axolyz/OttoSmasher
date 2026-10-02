import React,{useEffect,useRef,useState} from 'react';
import {Button,Space,Tabs,Tag} from 'antd';
import {request} from './Workspace';

export function useSearchResults(onError:(e:any)=>void, pageSize=100) {
  const [tabs,setTabs]=useState<any[]>([]),[active,setActive]=useState(''),[result,setResult]=useState<any>(null);
  const [offset,setOffset]=useState(0),[loading,setLoading]=useState(false),[revision,setRevision]=useState(0);
  const serial=useRef(0),scrollTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const presentation=useRef(new Map<string,number>()),renderTimes=useRef(new Map<string,number>());
  useEffect(()=>{if(result?.session_id&&presentation.current.has(result.session_id)){const began=presentation.current.get(result.session_id)!;const frame=requestAnimationFrame(()=>{presentation.current.delete(result.session_id);const elapsed=performance.now()-began;renderTimes.current.set(result.session_id,elapsed);setResult((old:any)=>old?.session_id===result.session_id?{...old,ui_elapsed_ms:elapsed}:old)});return()=>cancelAnimationFrame(frame)}},[result?.session_id]);
  useEffect(()=>{let dead=false;request('/api/library-tools/search-results').then(rows=>{if(dead)return;setTabs(rows);const last=rows.find((r:any)=>r.state?.active);if(last){setOffset(last.state.offset||0);setActive(last.id)}}).catch(onError);return()=>{dead=true;clearTimeout(scrollTimer.current)}},[]);
  useEffect(()=>{const seq=++serial.current;if(!active){setResult(null);return;}setLoading(true);const controller=new AbortController();
    request(`/api/library-tools/search-results/${active}?offset=${offset}&limit=${pageSize}`,undefined,controller.signal).then(data=>{if(seq===serial.current){setResult({...data,session_id:active,ui_elapsed_ms:renderTimes.current.get(active)});void request(`/api/library-tools/search-results/${active}/state`,{active:true,offset}).catch(onError)}}).catch(e=>{if(!controller.signal.aborted)onError(e)}).finally(()=>{if(seq===serial.current)setLoading(false)});
    return()=>controller.abort();
  },[active,offset,revision,pageSize]);
  async function add(kind:string,query:any,data:any){const {_ui_started_at,...persisted}=data;const saved=data.session || await request('/api/library-tools/search-results',{kind,query,result:persisted});if(_ui_started_at)presentation.current.set(saved.id,_ui_started_at);setTabs(old=>[...old,saved]);setResult({...data,session_id:saved.id,kind,total:data.total ?? data.results.length,state:{}});setOffset(0);setActive(saved.id)}
  function browse(){if(active)void request(`/api/library-tools/search-results/${active}/state`,{active:false}).catch(onError);setActive('');setResult(null)}
  async function close(id:string){const response=await fetch('/api/library-tools/search-results/'+id,{method:'DELETE'});if(!response.ok)throw Error('关闭结果标签失败');setTabs(old=>old.filter(t=>t.id!==id));if(active===id){setActive('');setResult(null)}}
  function remember(state:any){if(!active)return;setTabs(old=>old.map(t=>t.id===active?{...t,state:{...t.state,...state}}:t));void request(`/api/library-tools/search-results/${active}/state`,state).catch(onError)}
  function scroll(top:number){setTabs(old=>old.map(t=>t.id===active?{...t,state:{...t.state,scroll:top}}:t));clearTimeout(scrollTimer.current);const id=active;scrollTimer.current=setTimeout(()=>{if(id)void request(`/api/library-tools/search-results/${id}/state`,{scroll:top}).catch(onError)},250)}
  return {tabs,active,result,loading,reload:()=>setRevision(r=>r+1),offset,setOffset,add,browse,remember,scroll,
    bar:<Tabs size='small' type='editable-card' hideAdd activeKey={active} onChange={key=>{if(!key)browse();else{setResult(null);setOffset(tabs.find(t=>t.id===key)?.state?.offset||0);setActive(key)}}} onEdit={(key,action)=>{if(action==='remove')void close(String(key)).catch(onError)}}
      items={[{key:'',label:'浏览',closable:false},...tabs.map(t=>({key:t.id,label:`${t.title} (${t.count})`,closable:true}))]}/>};
}

export function ResultStatus({result,onRepeat}:{result:any;onRepeat:()=>void}) {
  if(!result)return null;
  return <Space size='small' wrap><Tag>固定结果 · {result.total} 项</Tag><small>固定成员与排序</small>{(result.elapsed_seconds!=null || result.elapsed_ms!=null)&&<small>后端 {(result.elapsed_seconds ?? result.elapsed_ms/1000).toFixed(3)} 秒{result.ui_elapsed_ms!=null?` · 显示 ${(result.ui_elapsed_ms/1000).toFixed(3)} 秒`:''}</small>}<Button size='small' onClick={onRepeat}>用这些条件再搜</Button>{result.approximate&&<Tag color='orange'>近似检索{result.truncated?' · 候选已截断':''}</Tag>}</Space>;
}
