import { defineConfig } from "vite";
import path from "node:path";
export default defineConfig({
  plugins: [{name:"edition-modules", generateBundle() {
    this.emitFile({type:"asset",fileName:"edition-modules.json",source:JSON.stringify((process.env.OTTO_ARCHIVED || "").split(",").filter(Boolean).sort())});
    this.emitFile({type:"asset",fileName:"archive-included.json",source:JSON.stringify([...this.getModuleIds()].filter(id=>id.includes("/archive/")))});
  }}],
  resolve: { dedupe: ["react", "react-dom", "antd", "@ant-design/icons"], alias: { "otto-archived-alignment": path.resolve(import.meta.dirname,
    (process.env.OTTO_ARCHIVED || "").split(",").includes("native-alignment")
      ? "../archive/native_alignment/NativeAlignment.tsx" : "src/ArchivedAlignmentDisabled.tsx") } },
  base: "/helper/",
  build: {
    outDir: "dist",
    rollupOptions: {
      onwarn(warning, warn) {
        if (
          warning.code === "MODULE_LEVEL_DIRECTIVE" &&
          warning.message.includes("use client")
        )
          return;
        warn(warning);
      },
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            if (id.includes("wavesurfer")) return "audio";
            if (
              id.includes("antd") ||
              id.includes("@ant-design") ||
              id.includes("@rc-component") ||
              id.includes("rc-")
            )
              return "ui";
            return "vendor";
          }
        },
      },
    },
  },
});
