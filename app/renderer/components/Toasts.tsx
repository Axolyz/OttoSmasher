// 提示条：改完即存的操作在这里给“撤销”（UI_PLAN §5）。
import { useApp } from "../state/store";
import s from "./Toasts.module.css";

export function Toasts() {
  const toasts = useApp((st) => st.toasts);
  const dismiss = useApp((st) => st.dismiss);
  return (
    <div className={s.stack} role="status" aria-live="polite">
      {toasts.map((x) => (
        <div key={x.id} className={`${s.toast} ${x.tone === "error" ? s.error : ""}`}>
          <span>{x.text}</span>
          {x.action ? (
            <button
              type="button"
              className={s.action}
              onClick={() => {
                x.action!.run();
                dismiss(x.id);
              }}
            >
              {x.action.label}
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
