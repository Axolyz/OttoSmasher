import React, { useEffect, useState } from "react";
import { Alert, Select, Space } from "antd";
export default function StudioModelSelect(props: {value?: string; onChange: (v: string)=>void; style?: React.CSSProperties}) {
  const [state,setState]=useState<any>({available_models:[]});
  useEffect(()=> { let alive=true; fetch("/api/helper/studio").then(r=>r.json()).then(x=>{if(alive)setState(x)}).catch(e=>{if(alive)setState({error:String(e),available_models:[]})}); return ()=>{alive=false}; },[]);
  const models=state.available_models.filter((m:any)=>m.stems?.some((s:string)=>s.toLowerCase()==="vocals"));
  const chosen=models.find((m:any)=>m.name===props.value || m.aliases?.includes(props.value));
  return <Space orientation="vertical" style={{width:"100%"}}>
    <Select {...props} style={{width:"100%",...props.style}} value={chosen?.name} placeholder="选择 Studio 已下载的人声模型" options={models.map((m:any)=>({value:m.name,label:m.name}))} />
    {state.error && <Alert type="warning" title={state.error} />}
    {!state.error && props.value && !chosen && <small>原选择 {props.value} 未在 Studio 中安装，请选择模型。</small>}
  </Space>;
}
