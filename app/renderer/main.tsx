import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./shell/App";
import "./styles/tokens.css";

// 源码运行的开发版叫 OttoSmasher Dev（窗口标题、程序坞），和发布版一眼分得清；行为一样
if (window.otto.app.build === "source") document.title = "OttoSmasher Dev";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
