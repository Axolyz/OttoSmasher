// UI_PLAN §6.1 集合规则在统一列表组件上的验证（jsdom + 真实的指针/键盘事件序列）。
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CollectionList, type CollectionRow } from "./CollectionList";
import type { MenuSpec } from "./Menu";

interface Item extends CollectionRow {
  name: string;
}

const ITEMS: Item[] = [
  { id: "a", name: "Alpha" },
  { id: "b", name: "Bravo" },
  { id: "c", name: "Charlie", dead: true },
  { id: "d", name: "Delta" },
  { id: "e", name: "Echo" },
];

function Harness(props: {
  items?: Item[];
  initialChecked?: string[];
  initialFocus?: string | null;
  spy: {
    focus?: (id: string) => void;
    checked?: (ids: string[]) => void;
    checkAll?: () => void;
    primary?: (id: string) => void;
    enter?: (id: string) => void;
    del?: (ids: string[]) => void;
    group?: (id: string, open?: boolean) => void;
    menu?: (item: Item, target: { ids: string[]; multi: boolean }) => void;
    key?: (k: string) => boolean;
  };
}) {
  const [focus, setFocus] = useState<string | null>(props.initialFocus ?? null);
  const [checked, setChecked] = useState<Set<string>>(new Set(props.initialChecked ?? []));
  return (
    <CollectionList<Item>
      label="list"
      items={props.items ?? ITEMS}
      textValue={(i) => i.name}
      focus={focus}
      onFocus={(id) => {
        setFocus(id);
        props.spy.focus?.(id);
      }}
      checked={checked}
      onChecked={(n) => {
        setChecked(n);
        props.spy.checked?.([...n].sort());
      }}
      onCheckAll={props.spy.checkAll}
      onPrimary={props.spy.primary}
      onEnter={props.spy.enter}
      onDelete={props.spy.del}
      onGroup={props.spy.group}
      isGroupOpen={() => true}
      onKey={props.spy.key ? (e) => props.spy.key!(e.key) : undefined}
      menu={(item, target): MenuSpec => {
        props.spy.menu?.(item, target);
        return { head: target.multi ? `checked ${target.ids.length}` : `on ${item.name}`, items: [{ id: "x", label: "Do", run: () => {} }] };
      }}
      renderItem={(i) => <span>{i.name}</span>}
      renderGroup={(i) => <span>{i.name}</span>}
      checkLabel={(i) => `check ${i.name}`}
      rowTestId="row"
    />
  );
}

const row = (name: string) => screen.getByText(name).closest<HTMLElement>("[data-key]")!;
const box = (name: string) => within(row(name)).getByRole("checkbox", { hidden: true });
const state = () =>
  ["Alpha", "Bravo", "Charlie", "Delta", "Echo"].map((n) => {
    const r = row(n);
    return `${n[0]}${r.hasAttribute("data-focus") ? "F" : ""}${r.hasAttribute("data-checked") ? "C" : ""}`;
  });

afterEach(cleanup);

describe("CollectionList（UI_PLAN §6.1）", () => {
  it("单击 = 焦点，从不改变勾选（即使已有勾选）", async () => {
    const u = userEvent.setup();
    const spy = { focus: vi.fn(), checked: vi.fn() };
    render(<Harness spy={spy} initialChecked={["a"]} />);
    await u.click(row("Bravo"));
    expect(spy.focus).toHaveBeenLastCalledWith("b");
    expect(spy.checked).not.toHaveBeenCalled();
    expect(state()).toEqual(["AC", "BF", "C", "D", "E"]);
  });

  it("复选框切换勾选，不改变焦点", async () => {
    const u = userEvent.setup();
    const spy = { focus: vi.fn(), checked: vi.fn() };
    render(<Harness spy={spy} initialFocus="a" />);
    await u.click(box("Delta"));
    expect(spy.checked).toHaveBeenLastCalledWith(["d"]);
    expect(spy.focus).not.toHaveBeenCalled();
    expect(state()).toEqual(["AF", "B", "C", "DC", "E"]);
  });

  it("⌘+单击切换勾选、不改焦点；Shift+单击从锚点连续勾选并跳过失效项", async () => {
    const u = userEvent.setup();
    const spy = { focus: vi.fn(), checked: vi.fn() };
    render(<Harness spy={spy} initialFocus="e" />);
    await u.keyboard("{Meta>}");
    await u.click(row("Alpha"));
    await u.keyboard("{/Meta}");
    expect(spy.checked).toHaveBeenLastCalledWith(["a"]);
    await u.keyboard("{Shift>}");
    await u.click(row("Delta"));
    await u.keyboard("{/Shift}");
    expect(spy.checked).toHaveBeenLastCalledWith(["a", "b", "d"]);
    expect(spy.focus).not.toHaveBeenCalled();
  });

  it("↑↓ 移动焦点并打开、跳过失效项；Shift+↓ 移动并勾选", async () => {
    const u = userEvent.setup();
    const spy = { focus: vi.fn(), checked: vi.fn() };
    render(<Harness spy={spy} />);
    await u.click(row("Bravo"));
    await u.keyboard("{ArrowDown}");
    expect(spy.focus).toHaveBeenLastCalledWith("d"); // c 失效，跳过
    await u.keyboard("{Shift>}{ArrowDown}{/Shift}");
    expect(spy.focus).toHaveBeenLastCalledWith("e");
    expect(spy.checked).toHaveBeenLastCalledWith(["e"]);
    await u.keyboard("{ArrowUp}");
    expect(spy.focus).toHaveBeenLastCalledWith("d");
  });

  it("X 切换焦点项；⌘A 勾选全部匹配；Esc 清空；Delete 删勾选，无勾选删焦点", async () => {
    const u = userEvent.setup();
    const spy = { checked: vi.fn(), checkAll: vi.fn(), del: vi.fn() };
    render(<Harness spy={spy} />);
    await u.click(row("Bravo"));
    await u.keyboard("{Delete}");
    expect(spy.del).toHaveBeenLastCalledWith(["b"]);
    await u.keyboard("x");
    expect(spy.checked).toHaveBeenLastCalledWith(["b"]);
    await u.keyboard("{Meta>}a{/Meta}");
    expect(spy.checkAll).toHaveBeenCalledTimes(1);
    await u.keyboard("{Delete}");
    expect(spy.del).toHaveBeenLastCalledWith(["b"]);
    await u.keyboard("{Escape}");
    expect(spy.checked).toHaveBeenLastCalledWith([]);
  });

  it("失效项不可勾选", () => {
    render(<Harness spy={{}} />);
    expect((box("Charlie") as HTMLInputElement).disabled).toBe(true);
  });

  it("双击 = 主动作；Enter = onEnter；页面键先于通用键", async () => {
    const u = userEvent.setup();
    const spy = { primary: vi.fn(), enter: vi.fn(), key: vi.fn((k: string) => k === " ") };
    render(<Harness spy={spy} />);
    await u.dblClick(row("Delta"));
    expect(spy.primary).toHaveBeenLastCalledWith("d");
    await u.keyboard("{Enter}");
    expect(spy.enter).toHaveBeenLastCalledWith("d");
    await u.keyboard(" ");
    expect(spy.key).toHaveBeenCalledWith(" ");
  });

  it("右键：在勾选集里且 ≥2 → 对象是勾选集；否则只这一项；不改变勾选和焦点；该行描边", async () => {
    const u = userEvent.setup();
    const spy = { focus: vi.fn(), checked: vi.fn(), menu: vi.fn() };
    render(<Harness spy={spy} initialChecked={["a", "b"]} initialFocus="e" />);
    await u.pointer({ keys: "[MouseRight]", target: row("Alpha") });
    expect(spy.menu).toHaveBeenLastCalledWith(expect.objectContaining({ id: "a" }), { ids: ["a", "b"], multi: true });
    expect(await screen.findByText("checked 2")).toBeTruthy();
    expect(row("Alpha").hasAttribute("data-menu")).toBe(true);
    expect(row("Bravo").hasAttribute("data-menu")).toBe(true);
    await u.keyboard("{Escape}");
    await act(async () => {});
    expect(spy.checked).not.toHaveBeenCalled(); // Esc 先关菜单，不清空勾选
    expect(row("Alpha").hasAttribute("data-menu")).toBe(false);
    await u.pointer({ keys: "[MouseRight]", target: row("Delta") });
    expect(spy.menu).toHaveBeenLastCalledWith(expect.objectContaining({ id: "d" }), { ids: ["d"], multi: false });
    expect(spy.focus).not.toHaveBeenCalled();
    expect(spy.checked).not.toHaveBeenCalled();
  });

  it("分组行：单击展开收起、← → 收起展开；不能勾选，↑↓ 经过它不改变查看对象", async () => {
    const u = userEvent.setup();
    const spy = { group: vi.fn(), focus: vi.fn() };
    const items: Item[] = [{ id: "g:1", kind: "group", name: "Group One" }, ...ITEMS.slice(0, 2)];
    render(<Harness spy={spy} items={items} />);
    await u.click(screen.getByText("Group One"));
    expect(spy.group).toHaveBeenLastCalledWith("g:1");
    await u.keyboard("{ArrowLeft}");
    expect(spy.group).toHaveBeenLastCalledWith("g:1", false);
    await u.keyboard("{ArrowRight}");
    expect(spy.group).toHaveBeenLastCalledWith("g:1", true);
    expect(within(screen.getByText("Group One").closest("[data-key]")!).queryByRole("checkbox")).toBeNull();
    expect(spy.focus).not.toHaveBeenCalled();
    await u.keyboard("{ArrowDown}");
    expect(spy.focus).toHaveBeenLastCalledWith("a");
  });
});
