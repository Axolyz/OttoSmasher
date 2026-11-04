// 全局兜底（所有者 2026-11-04）：界面渲染出错时 React 会卸载整棵界面，只剩黑屏。这里接住：说明情况、显示错误、写进日志、可以重新加载。
// 兜底画面不用项目组件（按钮用原生的）：出错的可能正是它们。
import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../i18n";
import s from "./Shell.module.css";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  override state = { error: null as Error | null };

  static getDerivedStateFromError(thrown: unknown) {
    return { error: thrown instanceof Error ? thrown : new Error(String(thrown)) };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    // 接住之后就不算未捕获的错误了：端到端测试靠这一行的前缀发现界面崩溃（e2e/helpers.ts）
    console.error(`otto-render-crash: ${error.message}`);
    window.otto.app.reportRendererError({ message: error.message, stack: error.stack ?? "", componentStack: info.componentStack ?? "" });
  }

  override render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className={s.crash} role="alert" data-testid="crash-screen">
        <h1 className={s.crashTitle}>{t("crash.title")}</h1>
        <p>{t("crash.body")}</p>
        <pre className={s.crashError} data-testid="crash-error">
          {error.message}
        </pre>
        <p className={s.muted}>{t("crash.logged")}</p>
        <button type="button" className={s.crashReload} onClick={() => window.otto.app.reload()} data-testid="crash-reload">
          {t("crash.reload")}
        </button>
      </div>
    );
  }
}
