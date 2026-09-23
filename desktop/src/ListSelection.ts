import { useEffect, useRef, useState } from "react";
import type { Dispatch, Key, MouseEvent, SetStateAction } from "react";

/** Explicit, temporary multi-selection. Browsing focus is never a batch selection. */
export function useListSelection<K extends Key>(
  selected: K[],
  setSelected: Dispatch<SetStateAction<K[]>>,
  visible: K[],
  retainOutside = false,
) {
  const [enabled, setEnabled] = useState(false);
  const anchor = useRef<K | null>(null);
  const signature = JSON.stringify(visible);
  useEffect(() => {
    if (retainOutside) {
      anchor.current = null;
      return;
    }
    setSelected((old) => {
      const next = old.filter((id) => visible.includes(id));
      return next.length === old.length ? old : next;
    });
    anchor.current = null;
  }, [signature, retainOutside]);
  const finish = () => {
    setSelected([]);
    setEnabled(false);
    anchor.current = null;
  };
  const begin = (id: K) => {
    setEnabled(true);
    setSelected([id]);
    anchor.current = id;
  };
  const click = (id: K, e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("button,a,input,.ant-select"))
      return true;
    if (!enabled && !e.metaKey && !e.ctrlKey && !e.shiftKey) return false;
    setEnabled(true);
    if (
      e.shiftKey &&
      anchor.current !== null &&
      visible.includes(anchor.current)
    ) {
      const a = visible.indexOf(anchor.current),
        b = visible.indexOf(id);
      setSelected([
        ...new Set(visible.slice(Math.min(a, b), Math.max(a, b) + 1)),
      ]);
    } else {
      setSelected((old) =>
        old.includes(id) ? old.filter((v) => v !== id) : [...old, id],
      );
      anchor.current = id;
    }
    return true;
  };
  const menu = (id: K) =>
    enabled
      ? [
          {
            key: "selection-all",
            label: "全选当前列表",
            onClick: () => setSelected([...new Set(visible)]),
          },
          { key: "selection-exit", label: "退出多选", onClick: finish },
        ]
      : [{ key: "selection-start", label: "多选", onClick: () => begin(id) }];
  const select = (ids: K[]) => { setEnabled(true); setSelected([...new Set(ids)]); };
  return { enabled, begin, finish, click, menu, select };
}
