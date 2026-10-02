import React, { useState } from "react";
import {
  App,
  Button,
  Checkbox,
  Dropdown,
  Modal,
  Select,
  Space,
  Tooltip,
} from "antd";
import { PlayCircleOutlined, AimOutlined } from "@ant-design/icons";
import { request } from "./Workspace";
export default function SpeechHits({
  hits,
  play,
  locate,
  source,
  file,
  changed,
  onError,
  bpm,
}: {
  hits: any[];
  play: (h: any, q: boolean, context: boolean, loop?: boolean) => void;
  locate: (h: any) => void;
  source: (h: any) => void;
  file: (p: string) => void;
  changed: () => void;
  onError: (e: any) => void;
  bpm: number | null;
}) {
  const { message } = App.useApp();
  const [expanded, setExpanded] = useState(false),
    [context, setContext] = useState(false),
    [save, setSave] = useState<any>(null),
    [nature, setNature] = useState("speech"),
    [busy, setBusy] = useState(false);
  const action = async (h: any, a: string) => {
    if(h.disabled)return;
    setBusy(true);
    try {
      if(h.kind==='pitch'){
        const selection=await request('/api/samples/pitch-hit/selection',{asset_id:h.asset_id,start:h.file_start,end:h.file_end,...(h.material_id?{sample_id:h.material_id}:{source_asset_id:h.source_asset_id})});
        if(a==='save')await request('/api/samples/selection/save',{selection,nature});
        else if(a==='flatten')await request('/api/samples/selection/flatten',{selection,mode:'all'});
        message.success(a==='flatten'?'拉平已排队；当前结果保持不变':'已保存为采样；当前结果保持不变');
        setSave(null);return;
      }
      const r = await request("/api/samples/speech-hit", {
        hit: h,
        action: a,
        bpm,
        nature,
      });
      if (r.path) file(r.path);
      if(a!=='flatten')changed();
      else message.success('拉平已排队；当前结果保持不变');
      if (a === "save") setSave(null);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      onClick={(e) => { if ((e.target as HTMLElement).closest("button,input,label,.ant-select,.ant-modal-root")) e.stopPropagation(); }}
      onContextMenu={(e) => e.stopPropagation()}
    >
      <small>{hits.length} 处命中</small>
      {(expanded ? hits : hits.slice(0, 3)).map((h, i) => (
        <Dropdown
          key={h.id}
          trigger={["contextMenu"]}
          menu={{
            items: [
              {
                key: "loop",
                label: "循环命中区",
                onClick: () => play(h, false, context, true),
              },
              { key: "source", label: "返回原片", onClick: () => source(h) },
              { key: "save", label: "保存命中区…", onClick: () => setSave(h) },
              {
                key: "flatten",
                label: "拉平命中区",
                onClick: () => action(h, "flatten"),
              },
              {
                key: "raw",
                label: "导出原声 WAV",
                onClick: () => action(h, "export"),
              },
              {
                key: "warped",
                label: "导出卡拍 WAV",
                onClick: () => action(h, "export-quantized"),
              },
              {
                key: "reaper",
                label: "复制 REAPER 交接",
                onClick: () => action(h, "reaper"),
              },
            ].filter(item=>!h.disabled && (h.kind!=="pitch" || ["loop","source","save","flatten"].includes(item.key))),
          }}
        >
          <div>
            <Space size={2}>
              <Tooltip title="左键原声／右键卡拍">
                <Button
                  disabled={h.disabled}
                  size="small"
                  type="text"
                  aria-label={`播放命中 ${i + 1}`}
                  icon={<PlayCircleOutlined />}
                  onClick={() => play(h, false, context)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    play(h, h.kind!=="pitch", context);
                  }}
                />
              </Tooltip>
              <Button
                disabled={h.disabled}
                type="text"
                size="small"
                icon={<AimOutlined />}
                onClick={() => locate(h)}
              >
                {h.start.toFixed(2)}–{h.end.toFixed(2)}s
                {h.rhythm_evidence && <Tooltip title={`平均偏差 ${h.rhythm_evidence.mean_deviation.toFixed(3)} · ${h.rhythm_evidence.basis === "beats" ? "拍" : "归一化形状"}；占格冲突 ${h.rhythm_evidence.occupancy_collisions?.flat().length || 0}；变速惩罚 ${(h.rhythm_evidence.speed_penalty || 0).toFixed(3)}`}><small style={{color:h.match_kind === "approximate"?"#e7bd76":"#9dccac",marginLeft:6}}>{h.match_kind === "approximate"?"近似":"严格"}{h.rhythm_evidence.candidate?.speech_playback_speed != null ? ` · ${h.rhythm_evidence.candidate.speech_playback_speed.toFixed(3)}×` : ""}</small></Tooltip>}
              </Button>
            </Space>
          </div>
        </Dropdown>
      ))}
      <Space wrap>
        {hits.length > 3 && (
          <Button
            size="small"
            type="link"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "收起" : "展开其余命中"}
          </Button>
        )}
        <Checkbox
          disabled={hits[0]?.kind === "pitch"}
          checked={context}
          onChange={(e) => setContext(e.target.checked)}
        >
          <small>前后 0.3s</small>
        </Checkbox>
      </Space>
      <Modal
        open={!!save}
        title="保存命中区"
        onCancel={() => setSave(null)}
        confirmLoading={busy}
        onOk={() => action(save, "save")}
      >
        <Select
          value={nature}
          onChange={setNature}
          style={{ width: "100%" }}
          options={[
            { value: "speech", label: "语音" },
            { value: "pitched", label: "调谐单音" },
            { value: "unpitched", label: "非调谐单音" },
            { value: "unclassified", label: "未分类" },
          ]}
        />
      </Modal>
    </div>
  );
}
