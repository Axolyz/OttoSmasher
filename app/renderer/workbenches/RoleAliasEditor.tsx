// 分离声部名 → 角色别名表（规格 05 §5.4、推定 A9）：分离结果登记时按声部名（不分大小写）预填角色；只作用于之后登记的声部。
// 草稿本地编辑，「保存」走编辑通道（可撤销）。
import { Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { Segmented } from "../components/Controls";
import { TextField } from "../components/Fields";
import { t } from "../i18n";
import s from "./RuleListEditor.module.css";

type Role = "vocal" | "sfx";
type Pair = [string, Role];

export function RoleAliasEditor(props: { value: Pair[]; defaultValue: Pair[]; onSave: (v: Pair[]) => Promise<void> }) {
  const [draft, setDraft] = useState<Pair[]>(props.value);
  const saved = JSON.stringify(props.value);
  useEffect(() => setDraft(props.value), [saved]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(draft) !== saved;
  const valid = draft.every(([n]) => n.trim());
  const set = (i: number, p: Pair) => setDraft((d) => d.map((x, j) => (j === i ? p : x)));
  return (
    <div className={s.editor} data-testid="role-aliases">
      <ol className={s.rules}>
        {draft.map(([name, role], i) => (
          <li key={i} className={s.rule}>
            <TextField value={name} onChange={(v) => set(i, [v, role])} label={t("aliases.stem", { n: i + 1 })} placeholder={t("aliases.stemPlaceholder")} mono invalid={!name.trim()} />
            <Segmented<Role>
              size="sm"
              value={role}
              onChange={(r) => set(i, [name, r])}
              label={t("aliases.role")}
              options={[
                { id: "vocal", label: t("role.vocal") },
                { id: "sfx", label: t("role.sfx") },
              ]}
            />
            <Button variant="flat" size="sm" icon={<X size={13} />} title={t("rules.remove")} onPress={() => setDraft((d) => d.filter((_, j) => j !== i))} />
          </li>
        ))}
      </ol>
      <div className={s.bar}>
        <Button size="sm" icon={<Plus size={13} />} onPress={() => setDraft((d) => [...d, ["", "vocal"]])}>
          {t("aliases.add")}
        </Button>
        <Button size="sm" variant="flat" icon={<RotateCcw size={13} />} isDisabled={JSON.stringify(draft) === JSON.stringify(props.defaultValue)} onPress={() => setDraft(props.defaultValue)}>
          {t("rules.restoreDefault")}
        </Button>
        <span className={s.grow} />
        <Button size="sm" variant="flat" isDisabled={!dirty} onPress={() => setDraft(props.value)}>
          {t("rules.discard")}
        </Button>
        <Button size="sm" variant="primary" isDisabled={!dirty || !valid} onPress={() => void props.onSave(draft.map(([n, r]) => [n.trim(), r]))} data-testid="aliases-save">
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}
