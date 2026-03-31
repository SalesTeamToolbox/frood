import { createPluginBundlerPresets } from "@paperclipai/plugin-sdk/bundlers";
import { build } from "esbuild";

const presets = createPluginBundlerPresets({
  pluginRoot: ".",
  uiEntry: "./src/ui/index.tsx",
  outdir: "./dist",
});

await build(presets.esbuild.ui);
console.log("UI build complete -> dist/ui/");
