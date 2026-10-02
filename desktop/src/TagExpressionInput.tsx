import React from 'react';
import {AutoComplete,Input,Tooltip} from 'antd';
export default function TagExpressionInput({value,onChange,tags,error}:{value:string;onChange:(v:string)=>void;tags:string[];error:string}) {
  // Completion replaces the last token only. The server remains the parser.
  const match=value.match(/(?:"(?:[^"\\]|\\.)*"?|[^\s()"]*)$/),tail=match?.[0]||'',prefix=value.slice(0,value.length-tail.length);
  const needle=tail.replace(/^"/,'').toLowerCase();
  const options=tags.filter(t=>t.toLowerCase().includes(needle)).slice(0,40).map(tag=>({value:prefix+JSON.stringify(tag),label:tag}));
  return <Tooltip title={error||'完整标签名；NOT > AND > OR。带空格或保留字的标签用双引号。'}>
    <AutoComplete value={value} onChange={onChange} options={options} style={{minWidth:260}}>
      <Input allowClear aria-label='标签布尔表达式' status={error?'error':undefined} placeholder='标签：a AND NOT b'/>
    </AutoComplete>
  </Tooltip>;
}
