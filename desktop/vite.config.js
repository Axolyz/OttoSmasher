import { defineConfig } from "vite";
export default defineConfig({
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
