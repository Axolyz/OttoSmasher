import React, { useEffect, useState } from "react";
import { Button, Collapse, Space, Tag } from "antd";
import Component from "otto-archived-alignment";
export function NativeAlignment(props: any) {
  const [enabled, setEnabled] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  useEffect(() => {
    fetch("/api/helper/capabilities").then(r=>r.json()).then(x=>setEnabled(x.archived.includes("native-alignment"))).catch(()=>{});
    fetch(`/api/samples/${props.id}/native-alignment`).then(r=>r.json()).then(x=>setResults(x.results || [])).catch(()=>{});
  }, [props.id]);
  if (enabled) return <Component {...props} />;
  if (!results.length) return null;
  return <Collapse items={[{key:"history",label:"历史字符／音节对齐",children:results.map(r=><div key={r.model}>
    <Tag>{r.model}</Tag>{r.stale ? "音源或模型已变化" : <Space wrap>{(r.segments || []).map((s:any,i:number)=><Button key={i} onClick={()=>props.locate(s.start,s.end,r.input?.asset?.role || "vocals")}>{s.text || s.label || i+1}</Button>)}</Space>}
  </div>)}]} />;
}
