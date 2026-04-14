import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = path.resolve(__dirname, "../..");
const runtimeRoot =
  process.env.VITE_TRACKING_VIEWER_STATE_ROOT ||
  path.resolve(__dirname, "../../.runtime/agent-runtime");
const pythonCommands = [
  process.env.VITE_TRACKING_VIEWER_PYTHON,
  process.env.PYTHON,
  "python3",
  "python",
].filter(Boolean);

function resolveProjectFile(rawPath) {
  if (!rawPath || typeof rawPath !== "string") {
    return "";
  }
  return path.isAbsolute(rawPath) ? rawPath : path.resolve(projectRoot, rawPath);
}

function viewerStateErrorPayload(message) {
  return {
    kind: "agent_viewer_state",
    session_id: null,
    available: false,
    message,
  };
}

function readViewerState() {
  let lastError = null;
  for (const command of pythonCommands) {
    try {
      const stdout = execFileSync(
        command,
        ["-m", "interfaces.viewer.stream", "--state-root", runtimeRoot],
        {
          cwd: projectRoot,
          encoding: "utf8",
          env: process.env,
        },
      );
      return JSON.parse(stdout);
    } catch (error) {
      lastError = error;
    }
  }

  const detail =
    lastError instanceof Error ? lastError.message : String(lastError || "unknown error");
  return viewerStateErrorPayload(`Viewer payload load failed: ${detail}`);
}

function displayFrameFromPayload(payload) {
  const trackingModule = payload?.modules?.["tracking-init"];
  if (trackingModule && typeof trackingModule === "object" && trackingModule.display_frame) {
    return trackingModule.display_frame;
  }
  const latestFrame = payload?.observation?.latest_frame;
  return latestFrame && typeof latestFrame === "object" ? latestFrame : null;
}

function registerViewerSnapshotRoutes(middlewares) {
  middlewares.use("/viewer-state.json", (_req, res) => {
    const payload = readViewerState();
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    res.end(JSON.stringify(payload, null, 2));
  });

  middlewares.use("/viewer-frame.jpg", (_req, res) => {
    const payload = readViewerState();
    const displayFrame = displayFrameFromPayload(payload);
    const imagePath = resolveProjectFile(String(displayFrame?.image_path || "").trim());
    if (!imagePath || !fs.existsSync(imagePath)) {
      res.statusCode = 404;
      res.setHeader("Cache-Control", "no-store");
      res.end();
      return;
    }
    res.statusCode = 200;
    res.setHeader("Content-Type", "image/jpeg");
    res.setHeader("Cache-Control", "no-store");
    fs.createReadStream(imagePath).pipe(res);
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
