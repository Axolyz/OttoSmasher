import {DraftNumber as InputNumber} from "./DraftNumber";
import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button,  Select, Space } from 'antd';
import { request } from './Workspace';

export default function AnnotationBoundaryEditor({ timeline, origin = 0, onSaved }: {
  timeline: any; origin?: number; onSaved: () => void;
}) {
  const [document, setDocument] = useState<any>(null), [selected, setSelected] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [action, setAction] = useState('');
  const current = useRef(document); current.current = document;
  const edits = useRef(new Map<string, any>());
  const generation = useRef(0);
  useEffect(() => { generation.current++; setDocument(null); setAction(''); setError(''); setBusy(false); }, [timeline]);
  async function begin() {
    const token = generation.current;
    setBusy(true); setError('');
    try {
      const [lo, hi] = timeline.ottoViewport();
      const items = timeline.ottoAnnotations().filter((a: any) => a.end != null && a.end > lo && a.start < hi && /^(subtitle-|timeline-)/.test(a.id));
      edits.current = new Map(items.map((a: any) => [a.annotation_id || a.id.replace(/^(subtitle-|timeline-)/, ''), a]));
      const ids = [...edits.current.keys()];
      if (!ids.length) throw Error('当前可见范围没有可编辑的字幕或区段');
      const doc = await request('/api/samples/edit/export', { objects: ids.map(id => ({ type: 'annotation', id })) });
      if (token === generation.current) {
        for(const o of doc.objects){const item=edits.current.get(o.id);timeline.ottoPatchAnnotation(item.id,convert(item,o.values.start,true),convert(item,o.values.end,true));}
        setDocument(doc); setSelected(ids[0]);
      }
    } catch (e) { if (token === generation.current) setError(String(e)); }
    finally { if (token === generation.current) setBusy(false); }
  }
  // Both forms and drags edit the document's declared clock; the waveform stays local.
  function convert(item: any, t: number, inverse = false) {
    if (!item?.edit_clock) return inverse ? t - origin : t + origin;
    if (item.edit_clock === 'asset') return inverse ? t - item.edit_offset + (item.viewport_offset || 0) : t - (item.viewport_offset || 0) + item.edit_offset;
    const knots = item.edit_knots, x = inverse ? 1 : 0, y = 1 - x;
    const value = inverse ? t : t - (item.viewport_offset || 0);
    let i = 0; while (i < knots.length - 2 && knots[i + 1][x] < value) i++;
    const a = knots[i], b = knots[i + 1];
    return a[y] + (value - a[x]) * (b[y] - a[y]) / (b[x] - a[x]) + (inverse ? item.viewport_offset || 0 : 0);
  }
  function change(id: string, start: number, end: number) {
    setDocument((doc: any) => ({ ...doc, objects: doc.objects.map((o: any) => o.id === id ? { ...o, values: { ...o.values, start, end } } : o) }));
  }
  useEffect(() => {
    if (!timeline) return;
    if (document) timeline.ottoSetAnnotationEditor((id: string, start: number, end: number) => {
      const key = id.replace(/^(subtitle-|timeline-)/, ''), item = edits.current.get(key);
      if (!current.current) return;
      setSelected(key); change(key, convert(item, start), convert(item, end));
    }, new Set(document.objects.map((o: any) => o.id).flatMap((id: string) => ['subtitle-' + id, 'timeline-' + id])));
    else timeline.ottoSetAnnotationEditor(null);
    return () => timeline.ottoSetAnnotationEditor(null);
  }, [timeline, !!document, origin]);
  async function save() {
    setBusy(true); setError('');
    try {
      const r = await request('/api/samples/edit/apply', document);
      if (!r.valid) throw Error(r.errors.map((e: any) => e.message).join('\n'));
      setAction(r.action_id); setDocument(null); onSaved();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  const chosen = document?.objects.find((o: any) => o.id === selected);
  function precise(field: string, value: number | null) {
    if (value == null || !chosen) return;
    const v = { ...chosen.values, [field]: value }, item = edits.current.get(selected);
    change(selected, v.start, v.end);
    if (v.end > v.start) timeline.ottoPatchAnnotation(item.id, convert(item, v.start, true), convert(item, v.end, true));
  }
  return <Space size='small' wrap>{document ? <>
    <Select aria-label='正在编辑的标注' style={{ width: 220 }} value={selected} onChange={setSelected}
      options={document.objects.map((o: any) => ({ value: o.id, label: o.values.text || o.values.tags?.join(' ') || o.id }))} />
    {chosen && <><span>{chosen.values.scope.type === 'asset' ? '资产秒' : '原片秒'}</span>
      <InputNumber aria-label='边界开始秒' style={{ width: 110 }} min={0} step={.001} precision={3} value={chosen.values.start} onChange={(v:any) => precise('start', v)} />—
      <InputNumber aria-label='边界结束秒' style={{ width: 110 }} min={0} step={.001} precision={3} value={chosen.values.end} onChange={(v:any) => precise('end', v)} /></>}
    <Button size='small' disabled={busy} onClick={() => { setDocument(null); onSaved(); }}>取消</Button>
    <Button size='small' type='primary' loading={busy} onClick={save}>保存边界</Button>
  </> : <Button size='small' loading={busy} disabled={!timeline} onClick={begin}>编辑字幕／区段边界</Button>}
    {action && <Button size='small' onClick={() => request('/api/samples/edit/undo', { action_id: action }).then(() => { setAction(''); onSaved(); }).catch(e => setError(String(e)))}>撤销边界修改</Button>}
    {error && <Alert type='error' message={error} />}
  </Space>;
}
