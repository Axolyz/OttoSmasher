import { FeatureFilters } from "./AcousticFeatures";
import BusinessTextEditor from "./BusinessTextEditor";
import React, { useEffect, useState } from "react";
import {
  Button,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Dropdown,
  Collapse,
} from "antd";
import { request } from "./Workspace";
export function LibraryFilters({
  singleTag, onSingleTag,
  scope,
  conditions,
  active,
  onSelect,
  report,
  tags,
  onTagsChanged,
}: {
  singleTag?: string;
  onSingleTag: (tag: string|undefined)=>void;
  scope: any;
  conditions: any[];
  active: any;
  onSelect: (v: any) => void;
  report: (e: any) => void;
  tags: string[];
  onTagsChanged: () => void;
}) {
  const [manageTags,setManageTags]=useState(false);
  const [sources, setSources] = useState<any[]>([]),
    [views, setViews] = useState<any[]>([]),
    [editing, setEditing] = useState<any>(null),
    [tagSearch, setTagSearch] = useState(""),
    [tagEdit, setTagEdit] = useState<any>(null);
  const load = () =>
    request("/api/library-tools/views")
      .then((r) =>
        setViews(
          r.sort(
            (a: any, b: any) =>
              (a.scope._position || 0) - (b.scope._position || 0) ||
              a.name.localeCompare(b.name),
          ),
        ),
      )
      .catch(report);
  useEffect(() => {
    void load();
    request("/api/samples/info")
      .then((v) => setSources(v.sources))
      .catch(report);
  }, []);
  async function save() {
    try {
      const r = await request("/api/library-tools/views", editing);
      onSelect({ ...editing, id: r.id });
      setEditing(null);
      await load();
    } catch (e) {
      report(e);
    }
  }
  async function remove(v: any) {
    try {
      await fetch("/api/library-tools/views/" + v.id, {
        method: "DELETE",
      }).then((r) => {
        if (!r.ok) throw Error("删除失败");
      });
      if (active?.id === v.id) onSelect(null);
      await load();
    } catch (e) {
      report(e);
    }
  }
  async function move(v: any, delta: number) {
    try {
      const i = views.findIndex((x) => x.id === v.id),
        j = i + delta;
      if (j < 0 || j >= views.length) return;
      const next = [...views];
      [next[i], next[j]] = [next[j], next[i]];
      for (let k = 0; k < next.length; k++)
        await request("/api/library-tools/views", {
          ...next[k],
          scope: { ...next[k].scope, _position: k + 1 },
        });
      await load();
    } catch (e) {
      report(e);
    }
  }
  const fresh = () => {
    const { intersections, ...plain } = scope;
    setEditing({ name: "", scope: { ...plain, conditions } });
  };
  return (
    <>
      <div className="sidebar-caption">筛选器</div>
      <Button
        type={!active ? "primary" : "text"}
        onClick={() => onSelect(null)}
      >
        全部范围
      </Button>
      {views.map((v) => (
        <Dropdown
          key={v.id}
          trigger={["contextMenu"]}
          menu={{
            items: [
              { key: "edit", label: "编辑", onClick: () => setEditing(v) },
              { key: "up", label: "上移", onClick: () => move(v, -1) },
              { key: "down", label: "下移", onClick: () => move(v, 1) },
              {
                key: "delete",
                label: "删除筛选器",
                danger: true,
                onClick: () => remove(v),
              },
            ],
          }}
        >
          <Button
            type={active?.id === v.id ? "primary" : "text"}
            onClick={() => onSelect(v)}
            title="在此范围内搜索"
          >
            {v.name}
          </Button>
        </Dropdown>
      ))}
      <Button onClick={fresh}>保存当前条件为筛选器</Button>
      <div className="sidebar-caption">标签范围</div>
      <Select aria-label="单标签范围" showSearch allowClear placeholder="全部标签" value={singleTag}
        onChange={onSingleTag} style={{width:'100%'}} optionFilterProp="label"
        options={tags.map(tag=>({value:tag,label:tag.replace(/^character:/,'角色：').replace(/^participants:/,'参与者（未分段）：')}))}/>
      <Button onClick={()=>setManageTags(true)}>管理标签…</Button>
      <Modal title="管理标签" open={manageTags} onCancel={()=>setManageTags(false)} footer={<Button onClick={()=>setManageTags(false)}>关闭</Button>}>
        <p>角色表示区间的单一角色；参与者表示多人或群体尚未分段。右键标签可查看重命名／移除操作。</p>

      <Input
        allowClear
        placeholder="查找标签"
        value={tagSearch}
        onChange={(e) => setTagSearch(e.target.value)}
      />
      <div className="sidebar-tags">
        {tags
          .filter((t) => t.toLowerCase().includes(tagSearch.toLowerCase()))
          .map((tag) => (
            <Dropdown
              key={tag}
              trigger={["contextMenu"]}
              menu={{
                items: [
                  {
                    key: "rename",
                    label: "全局重命名…",
                    onClick: () =>
                      setTagEdit({
                        tags: [tag],
                        operation: "rename",
                        global_scope: true,
                      }),
                  },
                  {
                    key: "delete",
                    label: "全局移除…",
                    danger: true,
                    onClick: () =>
                      setTagEdit({
                        tags: [tag],
                        operation: "remove",
                        global_scope: true,
                      }),
                  },
                ],
              }}
            >
              <Button
                type="text"

              >
                {tag}
              </Button>
            </Dropdown>
          ))}
      </div>
      </Modal>
      <Modal
        open={!!editing}
        title="筛选器"
        onCancel={() => setEditing(null)}
        onOk={save}
        okButtonProps={{ disabled: !editing?.name?.trim() }}
      >
        {editing && (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Input
              placeholder="名称"
              value={editing.name}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
            />
            <Input
              placeholder="名称／台词／备注包含"
              value={editing.scope.text || ""}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  scope: { ...editing.scope, text: e.target.value },
                })
              }
            />
            <Input.TextArea
              placeholder="标签条件：AND / OR / NOT"
              value={editing.scope.tag_expression || ""}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  scope: { ...editing.scope, tag_expression: e.target.value },
                })
              }
            />
            <Select
              style={{ width: "100%" }}
              value={editing.scope.nature || ""}
              options={[
                { value: "", label: "全部性质" },
                { value: "speech", label: "语音" },
                { value: "pitched", label: "调谐单音" },
                { value: "unpitched", label: "非调谐单音" },
                { value: "unclassified", label: "未分类" },
              ]}
              onChange={(v) =>
                setEditing({
                  ...editing,
                  scope: { ...editing.scope, nature: v },
                })
              }
            />
            <Select
              allowClear
              placeholder="所有原片"
              showSearch
              optionFilterProp="label"
              style={{ width: "100%" }}
              value={editing.scope.source_id}
              options={sources.map((s) => ({ value: s.id, label: s.title }))}
              onChange={(v) =>
                setEditing({
                  ...editing,
                  scope: { ...editing.scope, source_id: v },
                })
              }
            />
            <Input
              placeholder="作品（精确匹配）"
              value={editing.scope.work || ""}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  scope: { ...editing.scope, work: e.target.value },
                })
              }
            />
            <Space>
              <Switch
                checked={!!editing.scope.starred}
                onChange={(v) =>
                  setEditing({
                    ...editing,
                    scope: { ...editing.scope, starred: v },
                  })
                }
              />
              仅星标
            </Space>
            <Collapse
              size="small"
              items={[
                {
                  key: "properties",
                  label: "属性条件",
                  children: (
                    <FeatureFilters
                      mode={
                        editing.scope.nature === "pitched"
                          ? "pitched"
                          : "unpitched"
                      }
                      conditions={editing.scope.conditions || []}
                      onChange={(conditions) =>
                        setEditing({
                          ...editing,
                          scope: { ...editing.scope, conditions },
                        })
                      }
                      onPrepare={() =>
                        request("/api/library-tools/features", {
                          scope: editing.scope,
                        }).catch(report)
                      }
                    />
                  ),
                },
              ]}
            />
            <small>点击后与搜索框条件取交集。</small>
          </Space>
        )}
      </Modal>
      {tagEdit && (
        <TagEdit
          initial={tagEdit}
          onClose={() => setTagEdit(null)}
          onSaved={onTagsChanged}
          report={report}
        />
      )}
    </>
  );
}
export function TagEdit({
  initial,
  onClose,
  onSaved,
  report,
}: {
  initial: any;
  onClose: () => void;
  onSaved: () => void;
  report: (e: any) => void;
}) {
  const [sourceEdit, setSourceEdit] = useState<any>(null),
    [choices, setChoices] = useState<any[]>([]);
  useEffect(() => {
    if (initial.ids?.length)
      request("/api/ui/tags/options", { ids: initial.ids })
        .then(setChoices)
        .catch(report);
  }, []);
  const [tags, setTags] = useState<string[]>(initial.tags || []),
    [replacement, setReplacement] = useState(""),
    [preview, setPreview] = useState<any>(null),
    [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true);
    try {
      setPreview(
        await request("/api/ui/tags/preview", {
          ...initial,
          tags,
          replacement,
        }),
      );
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!preview) return;
    setBusy(true);
    try {
      const r = await request("/api/ui/tags/apply", {
        document: preview.document,
      });
      if (!r.valid) throw Error(JSON.stringify(r.errors));
      onSaved();
      onClose();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <BusinessTextEditor
        objects={sourceEdit}
        onClose={() => setSourceEdit(null)}
        onSaved={() => {
          setPreview(null);
          onSaved();
        }}
      />
      <Modal
        open
        title={`${initial.global_scope ? "全局" : `所选 ${initial.ids?.length || 0} 项`} · ${{ add: "添加标签", remove: "移除指定标签", rename: "重命名标签" }[initial.operation as "add" | "remove" | "rename"]}`}
        onCancel={onClose}
        onOk={preview ? save : check}
        okText={preview ? "应用修改" : "预览影响"}
        confirmLoading={busy}
        okButtonProps={{ disabled: !tags.length }}
      >
        <Select
          mode={initial.operation === "remove" ? "multiple" : "tags"}
          placeholder="选择标签（显示本地与继承数量）"
          options={choices.map((t) => ({
            value: t.tag,
            label: `${t.tag} · 本地 ${t.local} / 继承 ${t.inherited}`,
            disabled:
              initial.operation === "remove" &&
              !t.local &&
              !initial.global_scope,
          }))}
          style={{ width: "100%" }}
          value={tags}
          onChange={(v) => {
            setTags(v);
            setPreview(null);
          }}
        />
        {initial.operation === "rename" && (
          <Input
            placeholder="新名称"
            value={replacement}
            onChange={(e) => {
              setReplacement(e.target.value);
              setPreview(null);
            }}
          />
        )}
        {preview && (
          <p>
            修改 {preview.affected} 个对象，可通过资料编辑历史撤销。
            {preview.inherited.length > 0 &&
              `另有 ${preview.inherited.length} 项继承标签：所选采样操作不移除继承标签，请从详情标签的来源进入原片／区段修改。`}
          </p>
        )}
        {preview && (
          <>
            <ul>
              {Object.entries(preview.tag_counts || {}).map(([tag, count]) => (
                <li key={tag}>
                  {tag}：{String(count)} 个本地／源对象
                </li>
              ))}
            </ul>
            {preview.inherited.slice(0, 30).map((t: any, i: number) => (
              <Button
                key={i}
                type="link"
                disabled={!t.annotation_id && !t.source_id}
                onClick={() =>
                  setSourceEdit([
                    {
                      type: t.annotation_id ? "annotation" : "source_labels",
                      id: t.annotation_id || t.source_id,
                    },
                  ])
                }
              >
                {t.tag} · 编辑{t.annotation_id ? "区间标签" : "原片属性"}来源
              </Button>
            ))}
          </>
        )}
      </Modal>
    </>
  );
}
