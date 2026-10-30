// 命令面板（规格 03 §3、UI_PLAN §8 的“同源入口”）：⌘K 打开（输入框里也生效）；输入几个字按子串过滤，↑↓ 选、回车执行、Esc 关。
// 命令来自各处已有的菜单（右键菜单、批量操作 ▾ 等同一份 MenuItems，子菜单展开成“父 › 子”），所以与菜单同源、不另起动作。
// 空输入时按分组列出（最近用过的在最上面）；有输入时按匹配程度排成一列，每条右边写它属于哪一组。
import { type ReactNode, useMemo, useState } from "react";
import {
  Autocomplete,
  Dialog,
  Header,
  Input,
  Menu as RacMenu,
  MenuItem,
  MenuSection,
  Modal,
  ModalOverlay,
  SearchField,
} from "react-aria-components";
import type { MenuItems } from "./Menu";
import s from "./Overlay.module.css";

export interface PaletteCommand {
  /** 在整个面板里唯一（最近用过的按它记） */
  key: string;
  label: string;
  /** 所属分组的标题（有输入时写在右边） */
  group: string;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  /** 额外的匹配词（不显示） */
  keywords?: string;
  run: () => void;
}

export interface PaletteSection {
  id: string;
  title: string;
  items: PaletteCommand[];
}

/** 菜单项展开成命令：子菜单写成“父 › 子”，分隔线去掉。 */
export function fromMenu(sectionId: string, group: string, items: MenuItems, prefix = ""): PaletteCommand[] {
  const out: PaletteCommand[] = [];
  for (const it of items) {
    if (it === "-") continue;
    const label = prefix ? `${prefix} › ${it.label}` : it.label;
    if (it.items) out.push(...fromMenu(`${sectionId}/${it.id}`, group, it.items, label));
    else if (it.run) out.push({ key: `${sectionId}/${it.id}`, label, group, shortcut: it.shortcut, danger: it.danger, disabled: it.disabled, run: it.run });
  }
  return out;
}

const norm = (x: string) => x.normalize("NFKC").toLowerCase();

/** 子串过滤：每个空格分开的词都要出现在“名称 + 分组 + 额外词”里；名称开头匹配的排最前，其次名称里含整个输入的。 */
export function rankCommands(all: PaletteCommand[], query: string): PaletteCommand[] {
  const q = norm(query.trim());
  if (!q) return all;
  const words = q.split(/\s+/);
  const scored: Array<[number, number, PaletteCommand]> = [];
  all.forEach((c, i) => {
    const label = norm(c.label);
    const hay = `${label} ${norm(c.group)} ${norm(c.keywords ?? "")}`;
    if (!words.every((w) => hay.includes(w))) return;
    const score = label.startsWith(q) ? 0 : label.includes(q) ? 1 : words.every((w) => label.includes(w)) ? 2 : 3;
    scored.push([score + (c.disabled ? 10 : 0), i, c]);
  });
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  return scored.map((x) => x[2]);
}

export function CommandPalette(props: {
  isOpen: boolean;
  onClose: () => void;
  sections: PaletteSection[];
  /** 按输入临时生成的命令（例如输入数字 → “BPM 设为 …”），排在最前 */
  extra?: (query: string) => PaletteCommand[];
  onRun?: (cmd: PaletteCommand) => void;
  label: string;
  placeholder: string;
  empty: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const all = useMemo(() => props.sections.flatMap((x) => x.items), [props.sections]);
  const found = useMemo(() => {
    if (!query.trim()) return null;
    return [...(props.extra?.(query) ?? []), ...rankCommands(all, query)];
  }, [all, query, props]);
  const byKey = useMemo(() => {
    const m = new Map<string, PaletteCommand>();
    for (const c of [...all, ...(found ?? [])]) m.set(c.key, c);
    return m;
  }, [all, found]);
  const shown = found ? [{ id: "found", title: "", items: found }] : props.sections.filter((x) => x.items.length);
  const disabled = shown.flatMap((x) => x.items.filter((c) => c.disabled).map((c) => `${x.id}\x1f${c.key}`));
  const close = () => {
    setQuery("");
    props.onClose();
  };
  const run = (id: string) => {
    const cmd = byKey.get(id.split("\x1f")[1] ?? "");
    if (!cmd || cmd.disabled) return;
    close();
    props.onRun?.(cmd);
    // 面板关掉、焦点回到原处之后再执行（命令可能再打开别的对话框）
    setTimeout(cmd.run, 0);
  };

  return (
    <ModalOverlay isOpen={props.isOpen} onOpenChange={(o) => !o && close()} isDismissable className={s.paletteOverlay}>
      <Modal className={s.palette}>
        <Dialog className={s.paletteDialog} aria-label={props.label} data-testid="palette">
          <Autocomplete inputValue={query} onInputChange={setQuery}>
            <SearchField aria-label={props.label} autoFocus className={s.paletteField}>
              <Input
                className={s.paletteInput}
                placeholder={props.placeholder}
                data-testid="palette-input"
                onKeyDown={(e) => {
                  // 回车执行：有高亮项时由菜单执行；没有高亮项（过滤后第一项有时没拿到高亮，例如列表在输入后又重建）就执行第一个能用的
                  if (e.key !== "Enter" || e.currentTarget.getAttribute("aria-activedescendant")) return;
                  const sec = shown.find((x) => x.items.some((c) => !c.disabled));
                  const first = sec?.items.find((c) => !c.disabled);
                  if (!sec || !first) return;
                  e.preventDefault();
                  run(`${sec.id}\x1f${first.key}`);
                }}
              />
            </SearchField>
            <RacMenu
              className={s.paletteList}
              aria-label={props.label}
              disabledKeys={disabled}
              onAction={(k) => run(String(k))}
              renderEmptyState={() => <div className={s.paletteEmpty}>{props.empty}</div>}
              data-testid="palette-list"
            >
              {shown.map((sec) => (
                <MenuSection key={sec.id} id={sec.id}>
                  {sec.title ? <Header className={s.paletteHead}>{sec.title}</Header> : null}
                  {sec.items.map((c) => (
                    <MenuItem
                      key={c.key}
                      id={`${sec.id}\x1f${c.key}`}
                      textValue={c.label}
                      className={`${s.item} ${c.danger ? s.danger : ""}`}
                      data-testid="palette-item"
                      data-command={c.key}
                    >
                      <span className={s.paletteLabel}>{c.label}</span>
                      <span className={s.paletteMeta}>
                        {found ? <span className={s.paletteGroup}>{c.group}</span> : null}
                        {c.shortcut ? <kbd className={s.kbd}>{c.shortcut}</kbd> : null}
                      </span>
                    </MenuItem>
                  ))}
                </MenuSection>
              ))}
            </RacMenu>
          </Autocomplete>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
