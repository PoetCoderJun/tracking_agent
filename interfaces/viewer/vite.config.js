import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const viewerStateRoot =
  process.env.VITE_TRACKING_VIEWER_STATE_ROOT ||
  path.resolve(__dirname, "../../.runtime/agent-runtime/viewer");
const viewerStateFile = path.join(viewerStateRoot, "latest.json");
const viewerFrameFile = path.join(viewerStateRoot, "latest.jpg");

function emptyViewerState() {
  return JSON.stringify(
    {
      kind: "agent_viewer_state",
      session_id: null,
      available: false,
      message: "Viewer snapshot not written yet.",
    },
    null,
    2,
  );
}

function registerViewerSnapshotRoutes(middlewares) {
  middlewares.use("/viewer-state.json", (_req, res) => {
    const body = fs.existsSync(viewerStateFile)
      ? fs.readFileSync(viewerStateFile, "utf8")
      : emptyViewerState();
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    res.end(body);
  });

  middlewares.use("/viewer-frame.jpg", (_req, res) => {
    if (!fs.existsSync(viewerFrameFile)) {
      res.statusCode = 404;
      res.setHeader("Cache-Control", "no-store");
      res.end();
      return;
    }
    res.statusCode = 200;
    res.setHeader("Content-Type", "image/jpeg");
    res.setHeader("Cache-Control", "no-store");
    fs.createReadStream(viewerFrameFile).pipe(res);
  });
}

function localViewerFilesPlugin() {
  return {
    name: "local-viewer-files",
    configureServer(server) {
      registerViewerSnapshotRoutes(server.middlewares);
    },
    configurePreviewServer(server) {
      registerViewerSnapshotRoutes(server.middlewares);
    },
  };
}

export default defineConfig({
  plugins: [react(), localViewerFilesPlugin()],
  server: {
    host: "127.0.0.1",
    port: 4174,
  },
  preview: {
    host: "127.0.0.1",
    port: 4174,
  },
});
