import BusinessFields from "./BusinessFields";
import React, { useEffect, useState } from "react";
import { Alert, App, Button, Input, Modal, Space } from "antd";
import { request } from "./Workspace";

/** One business document protocol for bulk text editing and saved-data undo. */
export default function BusinessTextEditor({ objects, draft=null, onClose, onSaved }: {
  objects: { type: string; id: string }[] | null;
  draft?: any;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [advanced,setAdvanced]=useState(false);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<string | null>(null);
  const targets=objects||draft?.objects.map((o:any)=>({type:o.type,id:o.id}));
  useEffect(() => {
    if (!objects&&!draft) return;
    let cancelled = false;
    setBusy(true); setPreview(null); setError(""); setAction(null); setText("");
    (draft?Promise.resolve(draft):request("/api/samples/edit/export", { objects })).then(doc => {
      if (!cancelled) setText(JSON.stringify(doc, null, 2));
    }).catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [objects,draft]);
  async function run(apply: boolean) {
    setBusy(true); setError("");
    try {
      const doc = JSON.parse(text);
      const result = await request(`/api/samples/edit/${apply ? "apply" : "preview"}`, doc);
      setPreview(result);
      if (apply && result.valid) {
        setAction(result.action_id); onSaved();
        // Re-export the complete selection so omitted objects stay editable.
        const current = await request("/api/samples/edit/export", { objects:targets });
        setText(JSON.stringify(current, null, 2));
        message.success(result.action_id ? "资料已保存" : "没有变更");
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function undo() {
    setBusy(true);
    try {
      await request("/api/samples/edit/undo", { action_id: action });
      const current = await request("/api/samples/edit/export", { objects:targets });
      setText(JSON.stringify(current, null, 2)); setAction(null); setPreview(null); onSaved();
      message.success("已撤销保存的资料修改");
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return <Modal title="编辑所选资料" open={objects !== null || !!draft} onCancel={onClose} width={920}
    footer={<Space><Button onClick={onClose}>关闭</Button><Button disabled={!action || busy} onClick={undo}>撤销这次保存</Button>
      <Button disabled={busy || !text} onClick={() => run(false)}>预览变更</Button>
      <Button type="primary" loading={busy} disabled={!text} onClick={() => run(true)}>保存</Button></Space>}>
    <Button size="small" type="link" onClick={()=>setAdvanced(!advanced)}>{advanced?"返回表单":"高级批量 JSON"}</Button>
    {error && <Alert type="error" message={error} />}
    {advanced ? <Input.TextArea aria-label="业务资料 JSON" spellCheck={false} value={text} rows={18}
      style={{fontFamily: "monospace"}} onChange={e => { setText(e.target.value); setPreview(null); }} /> : text && (()=>{try{return <BusinessFields doc={JSON.parse(text)} onChange={doc=>{setText(JSON.stringify(doc,null,2));setPreview(null)}}/>}catch{return <Alert type="error" message="高级文本格式错误，请返回高级编辑修正"/>}})()}
    {preview && <div style={{maxHeight: 240, overflow: "auto", marginTop: 12}}>
      <Alert type={preview.valid ? "info" : "error"} message={preview.valid ? `${preview.changes.length} 个对象将改变；媒体文件不变` : preview.errors.map((x: any) => `${x.path}: ${x.message}`).join("\n")} />
      <pre>{JSON.stringify(preview.changes.map((c: any) => ({id: c.id, fields: c.fields})), null, 2)}</pre>
    </div>}
  </Modal>;
}
