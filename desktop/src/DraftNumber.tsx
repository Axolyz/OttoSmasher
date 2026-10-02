import React, { useEffect, useRef, useState } from "react";
import { InputNumber } from "antd";
/** Keep editing drafts (including empty/minus) separate from committed numeric values. */
export function DraftNumber(props: any) {
  const { value, onChange, allowEmpty, ...rest } = props;
  const [draft, setDraft] = useState<any>(value),
    [empty, setEmpty] = useState(false);
  const focused = useRef(false),
    optional = useRef(allowEmpty ?? (value === undefined || value === null));
  useEffect(() => {
    if (!focused.current) {
      setDraft(value);
      setEmpty(value === null && !optional.current);
    }
  }, [value]);
  return (
    <InputNumber
      {...rest}
      value={draft}
      status={empty && !optional.current ? "error" : rest.status}
      className={[
        rest.className,
        empty && !optional.current ? "otto-number-invalid" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onFocus={(e: any) => {
        focused.current = true;
        rest.onFocus?.(e);
      }}
      onBlur={(e: any) => {
        focused.current = false;
        rest.onBlur?.(e);
      }}
      onChange={(next: any) => {
        setDraft(next);
        setEmpty(next === null);
        if (next !== null || optional.current) onChange?.(next);
      }}
    />
  );
}
