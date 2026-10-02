import React, { useEffect, useState } from "react";
import { Alert, App, Button, Input, Modal, Space } from "antd";
import { request } from "./Workspace";

export default function FrontendDialog({ target, onClose }: {target: {cueId?: string} | null; onClose: () => void}) {
  const { message } = App.useApp();
  const [text, setText] = useState("");
  const [sentence, setSentence] = useState("京子が来た。");
  const [base, setBase] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const cueId = target?.cueId;
  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    setBase(null); setText(""); setError(""); setResult(null); setBusy(true);
    const load = cueId ? request("/api/samples/edit/export", {objects:[{type:"alignment_text",id:cueId}]}) : request("/api/samples/frontend/dictionary");
    load.then(r => { if (!cancelled) {setBase(r); setText(cueId ? r.objects[0].values.text : r.text);} })
      .catch(e => {if (!cancelled) setError(String(e));}).finally(() => {if (!cancelled) setBusy(false);});
    return () => {cancelled = true;};
  }, [target]);
  async function save() {
    setBusy(true); setError("");
    try {
      if (cueId) {
        const doc = {...base, objects: base.objects.map((o: any) => ({...o, values:{text}}))};
        const r = await request("/api/samples/edit/apply", doc);
        if (!r.valid) throw new Error(r.errors.map((e:any) => e.message).join("\n"));
        setBase(r.document.objects.length ? r.document : base);
      } else {
        setBase(await request("/api/samples/frontend/dictionary", {text, base_version:base.version}));
      }
      setResult(null); message.success(cueId ? "对齐文本已保存；原字幕保留，重新 FA 后采用新读音" : "用户辞典已编译并启用");
    } catch (e) {setError(String(e));} finally {setBusy(false);}
  }
  async function preview() {
    setBusy(true); setError("");
    try {setResult(await request("/api/samples/frontend/preview", {text:cueId ? text : sentence}));}
    catch (e) {setError(String(e));} finally {setBusy(false);}
  }
  return <Modal title={cueId ? "对齐文本 · 原字幕保持不变" : "工作区用户辞典"} width={820} open={target !== null} onCancel={onClose}
    footer={<Space><Button onClick={onClose}>关闭</Button><Button disabled={busy} onClick={preview}>预览 G2P</Button><Button type="primary" loading={busy} disabled={!base} onClick={save}>保存</Button></Space>}>
    <p>{cueId ? "填写日语或假名；音素只读，时间戳修订与重新 FA 结果分别保存。" : "每行：表记 + Tab + 片假名发音。保存成功后启用；预览使用已保存的辞典。"}</p>
    {error && <Alert type="error" message={error} />}
    <Input.TextArea aria-label={cueId ? "对齐文本" : "用户辞典文本"} rows={10} value={text} onChange={e => setText(e.target.value)}
      onKeyDown={e => {if (e.key === "Tab") {e.preventDefault(); const input=e.currentTarget; const a=input.selectionStart; const b=input.selectionEnd; setText(text.slice(0,a)+"\t"+text.slice(b)); requestAnimationFrame(() => input.setSelectionRange(a+1,a+1));}}} />
    {!cueId && <Input aria-label="辞典预览句子" value={sentence} onChange={e => setSentence(e.target.value)} style={{marginTop:12}} />}
    {result && <><p>生成音素（只读，可复制）</p><Input.TextArea readOnly value={result.phones.join(" ")} rows={3} />
      <small>前端：{result.version} · tsqyomi 已启用</small></>}
  </Modal>;
}
