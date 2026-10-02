import {DraftNumber as InputNumber} from "./DraftNumber";
import React from 'react';
import {Button,Checkbox,Form,Input,Select,Space} from 'antd';

export default function BusinessFields({doc,onChange}:{doc:any;onChange:(doc:any)=>void}) {
  const change=(index:number,patch:any)=>onChange({...doc,objects:doc.objects.map((o:any,i:number)=>i===index?{...o,values:{...o.values,...patch}}:o)});
  const names:any={sample:'采样资料',annotation:'时间标注',alignment_text:'对齐文本',sample_visual:'采样画面',source_visual:'原片默认画面',track_group:'轨道组',source_labels:'原片属性标签'};
  return <div style={{maxHeight:'60vh',overflowY:'auto'}}>{doc.objects.map((o:any,index:number)=>{
    const v=o.values,patch=(p:any)=>change(index,p);
    return <Form key={o.id} layout='vertical' style={{borderBottom:'1px solid #364250',paddingBottom:12}}>
      <strong>{names[o.type]}{v.title?' · '+v.title:''}</strong>
      {o.type==='sample'&&<><Form.Item label='名称'><Input value={v.title} onChange={e=>patch({title:e.target.value})}/></Form.Item><Form.Item label='备注'><Input.TextArea value={v.notes} onChange={e=>patch({notes:e.target.value})}/></Form.Item><Form.Item label='性质'><Select value={v.nature} onChange={nature=>patch({nature})} options={[['speech','语音'],['pitched','有音高'],['unpitched','无音高'],['unclassified','未分类']].map(([value,label])=>({value,label}))}/></Form.Item><Checkbox checked={v.starred} onChange={e=>patch({starred:e.target.checked})}>收藏</Checkbox></>}
      {o.type==='annotation'&&<><p>坐标：{v.scope.type==='asset'?'资产局部时间':'原片时间'}，单位秒</p><Space><InputNumber aria-label='标注开始秒' min={0} step={.01} value={v.start} onChange={(start:any)=>patch({start})}/><span>—</span><InputNumber aria-label='标注结束秒' min={0} step={.01} value={v.end} onChange={(end:any)=>patch({end})}/></Space><Form.Item label='适用范围'><Select value={v.scope.type} onChange={type=>patch({scope:{type,ids:[]}})} options={[{value:'source',label:'原片全部声音'},{value:'group',label:'指定轨道组'},{value:'asset',label:'具体声音资产'}]}/>{v.scope.type!=='source'&&<Select mode='tags' value={v.scope.ids} onChange={ids=>patch({scope:{...v.scope,ids}})} placeholder={v.scope.type==='group'?'如 dialogue':'资产 ID'} />}</Form.Item><Checkbox checked={v.delete} onChange={e=>patch({delete:e.target.checked})}>删除这条标注</Checkbox></>}
      {'text' in v&&<Form.Item label={o.type==='alignment_text'?'用于对齐的日语／假名':'文字'}><Input.TextArea rows={3} value={v.text} onChange={e=>patch({text:e.target.value})}/></Form.Item>}
      {'tags' in v&&<Form.Item label='标签'><Select aria-label='标签' mode='tags' style={{width:'100%'}} value={v.tags} onChange={tags=>patch({tags})}/></Form.Item>}
      {o.type==='track_group'&&<Form.Item label='轨道组'><Select mode='tags' value={v.groups} onChange={groups=>patch({groups})} options={['dialogue','music','effects'].map(value=>({value,label:value}))}/></Form.Item>}
      {o.type.endsWith('_visual')&&<><Form.Item label='画面模式'><Select value={v.mode||'inherit'} onChange={mode=>patch({mode:mode==='inherit'?null:mode,...(mode==='inherit'?{path:''}:{})})} options={[{value:'inherit',label:'恢复默认／继承'},{value:'sync',label:'同步视频'},{value:'image',label:'静态图片'},{value:'local_loop',label:'独立动画循环'}]}/></Form.Item>{v.mode&&<Form.Item label='画面文件'><Space.Compact style={{width:'100%'}}><Input value={v.path} onChange={e=>patch({path:e.target.value})}/><Button onClick={async()=>{const paths=await window.ottoDesktop?.pick();if(paths?.[0])patch({path:paths[0]})}}>选择文件</Button></Space.Compact><small>保存后在播放器预览；动画以声音为主时钟，循环画面保持静音。</small></Form.Item>}</>}
    </Form>;
  })}</div>;
}
