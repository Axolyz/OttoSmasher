// 分页表格：表头跨所有分页全选、半选态、不可勾选的行、Shift 连选（规格 06 §6.4）。
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { PagedTable } from "./PagedTable";

interface R {
  id: string;
  name: string;
  excluded?: boolean;
}
const ROWS: R[] = Array.from({ length: 7 }, (_, i) => ({ id: `r${i}`, name: `Line ${i}`, excluded: i === 2 }));

function Harness() {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  return (
    <>
      <PagedTable<R>
        label="preview"
        rows={ROWS}
        pageSize={3}
        checked={checked}
        onChecked={setChecked}
        isSelectable={(r) => !r.excluded}
        checkLabel={(r) => `check ${r.name}`}
        columns={[{ id: "name", label: "Name", isRowHeader: true, render: (r) => r.name }]}
      />
      <output data-testid="out">{[...checked].sort().join(",")}</output>
    </>
  );
}

afterEach(cleanup);
const header = () => screen.getByTestId("table-check-all").querySelector("input")!;
const out = () => screen.getByTestId("out").textContent;
const rowBox = (name: string) => within(screen.getByText(name).closest("[role=row]") as HTMLElement).getByRole("checkbox");

describe("PagedTable", () => {
  it("表头：全选覆盖所有分页（跳过不可勾选的行），再按一次全部清空；部分勾选时半选", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    expect(screen.getByTestId("table-page").textContent).toBe("1 / 3");
    await u.click(header());
    expect(out()).toBe("r0,r1,r3,r4,r5,r6");
    expect(header().checked).toBe(true);
    await u.click(rowBox("Line 0"));
    expect(header().indeterminate).toBe(true);
    expect(screen.getByTestId("table-checked").textContent).toContain("5");
    await u.click(header()); // 半选 → 全选
    expect(out()).toBe("r0,r1,r3,r4,r5,r6");
    await u.click(header());
    expect(out()).toBe("");
  });

  it("不可勾选的行：复选框禁用", () => {
    render(<Harness />);
    expect((rowBox("Line 2") as HTMLInputElement).disabled).toBe(true);
  });

  it("Shift+单击复选框：从上次勾选的行连续勾选（跨页）", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    await u.click(rowBox("Line 1"));
    await u.click(screen.getByRole("button", { name: /下一页|next/i }));
    await u.keyboard("{Shift>}");
    await u.click(rowBox("Line 4"));
    await u.keyboard("{/Shift}");
    expect(out()).toBe("r1,r3,r4");
  });
});
