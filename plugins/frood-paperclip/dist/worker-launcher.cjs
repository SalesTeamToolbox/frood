// CJS bootstrap launcher for Windows compatibility.
// fork() on Windows can't load ESM modules directly.
// We import the ESM worker and call startWorkerRpcHost explicitly
// (bypassing runWorker's import.meta.url check).
const { pathToFileURL } = require("node:url");
const path = require("node:path");
const workerPath = path.join(__dirname, "worker.js");

import(pathToFileURL(workerPath).href)
  .then(async (workerModule) => {
    // worker.js default export is the plugin definition from definePlugin()
    const plugin = workerModule.default;

    // Import startWorkerRpcHost from the SDK
    const sdk = await import("@paperclipai/plugin-sdk");
    sdk.startWorkerRpcHost({ plugin });
  })
  .catch((err) => {
    process.stderr.write(String(err) + "\n");
    process.exit(1);
  });
