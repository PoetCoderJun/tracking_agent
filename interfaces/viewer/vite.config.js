import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const projectRoot = path.resolve(__dirname, "../..");
const runtimeRoot =
  process.env.VITE_TRACKING_VIEWER_STATE_ROOT ||
  path.resolve(__dirname, "../../.runtime/agent-runtime");
const activeSessionFile = path.join(runtimeRoot, "active_session.json");
const perceptionSnapshotFile = path.join(runtimeRoot, "perception", "snapshot.json");

function readJson(filePath, fallback) {
  if (!fs.existsSync(filePath)) {
    return fallback;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function resolveProjectFile(rawPath) {
  if (!rawPath || typeof rawPath !== "string") {
    return "";
  }
  return path.isAbsolute(rawPath) ? rawPath : path.resolve(projectRoot, rawPath);
}

function resolveActiveSessionId() {
  const payload = readJson(activeSessionFile, null);
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const sessionId = String(payload.session_id || "").trim();
  return sessionId || null;
}

function sessionFile(sessionId) {
  return path.join(runtimeRoot, "sessions", sessionId, "session.json");
}

function trackingMemoryFile(sessionId) {
  return path.join(runtimeRoot, "tracking_memory", sessionId, "memory.json");
}

function trackingMemoryDisplayText(memoryValue) {
  const memory = memoryValue && typeof memoryValue === "object" ? memoryValue : {};
  const labels = [
    ["core", "核心特征"],
    ["front_view", "正面特征"],
    ["back_view", "背面特征"],
    ["distinguish", "区分点"],
  ];
  return labels
    .map(([key, label]) => {
      const value = String(memory[key] || "").trim();
      return value ? `${label}：${value}` : "";
    })
    .filter(Boolean)
    .join("\n");
}

function normalizeRecentFrames(snapshot) {
  const observations = Array.isArray(snapshot?.recent_camera_observations)
    ? snapshot.recent_camera_observations
    : [];
  return observations.map((observation) => {
    const payload = observation && typeof observation === "object" ? observation.payload || {} : {};
    const meta = observation && typeof observation === "object" ? observation.meta || {} : {};
    return {
      frame_id: String(payload.frame_id || observation?.id || "").trim(),
      timestamp_ms: Number(observation?.ts_ms || 0),
      image_path: String(payload.image_path || "").trim(),
      detections: Array.isArray(meta.detections) ? meta.detections : [],
    };
  });
}

function enrichedConversationHistory(session) {
  const rawHistory = Array.isArray(session?.conversation_history) ? session.conversation_history : [];
  const resultHistory = Array.isArray(session?.result_history) ? session.result_history : [];
  const debugByTimestamp = new Map();
  for (const item of resultHistory) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const timestamp = String(item.updated_at || "").trim();
    if (timestamp) {
      debugByTimestamp.set(timestamp, item);
    }
  }
  return rawHistory
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => {
      const normalized = {
        role: String(entry.role || "").trim(),
        text: String(entry.text || "").trim(),
        timestamp: String(entry.timestamp || "").trim(),
      };
      if (normalized.role === "assistant" && debugByTimestamp.has(normalized.timestamp)) {
        normalized.debug = debugByTimestamp.get(normalized.timestamp);
      }
      return normalized;
    });
}

function trackingStatus(latestResult, trackingState, streamStatus) {
  if (String(streamStatus?.status || "").trim() === "completed") {
    return { kind: "completed", label: "视频结束" };
  }
  if (String(trackingState?.pending_question || "").trim()) {
    return { kind: "seeking", label: "寻找中" };
  }
  const action =
    latestResult?.robot_response && typeof latestResult.robot_response === "object"
      ? latestResult.robot_response.action
      : latestResult?.decision || latestResult?.behavior;
  if (action === "wait") {
    return { kind: "seeking", label: "寻找中" };
  }
  const lifecycleStatus = String(trackingState?.lifecycle_status || "").trim();
  if (["scheduled", "running", "bound"].includes(lifecycleStatus)) {
    return { kind: "tracking", label: "跟踪中" };
  }
  if (lifecycleStatus === "seeking") {
    return { kind: "seeking", label: "寻找中" };
  }
  if (["track", "init"].includes(String(action || "").trim()) || latestResult?.target_id !== undefined) {
    return { kind: "tracking", label: "跟踪中" };
  }
  return { kind: "idle", label: "等待中" };
}

function resolveDisplayFrame(latestResult, trackingState, recentFrames) {
  const resolvedTargetId =
    latestResult?.target_id !== undefined && latestResult?.target_id !== null && latestResult?.target_id !== ""
      ? latestResult.target_id
      : trackingState?.latest_target_id;
  if (!Array.isArray(recentFrames) || !recentFrames.length || resolvedTargetId === undefined || resolvedTargetId === null || resolvedTargetId === "") {
    return null;
  }
  const resultFrameId = String(latestResult?.frame_id || "").trim();
  let displayFrame = null;
  if (resultFrameId) {
    displayFrame = [...recentFrames].reverse().find((frame) => String(frame.frame_id || "").trim() === resultFrameId) || null;
  }
  if (!displayFrame) {
    displayFrame = recentFrames[recentFrames.length - 1];
  }
  const detections = Array.isArray(displayFrame?.detections) ? displayFrame.detections : [];
  const targetBBox =
    Array.isArray(latestResult?.bbox) && latestResult.bbox.length === 4
      ? latestResult.bbox
      : (detections.find((detection) => String(detection?.track_id ?? detection?.target_id ?? "") === String(resolvedTargetId))
          ?.bbox || null);
  return {
    ...displayFrame,
    target_id: resolvedTargetId,
    bbox: targetBBox,
  };
}

function buildViewerState() {
  const sessionId = resolveActiveSessionId();
  if (!sessionId) {
    return {
      kind: "agent_viewer_state",
      session_id: null,
      available: false,
      message: "No active session yet.",
    };
  }

  const session = readJson(sessionFile(sessionId), null);
  if (!session || typeof session !== "object") {
    return {
      kind: "agent_viewer_state",
      session_id: sessionId,
      available: false,
      message: "Session not found yet.",
    };
  }

  const perceptionSnapshot = readJson(perceptionSnapshotFile, {});
  const streamStatus = perceptionSnapshot?.stream_status && typeof perceptionSnapshot.stream_status === "object"
    ? perceptionSnapshot.stream_status
    : {};
  const recentFrames = normalizeRecentFrames(perceptionSnapshot);
  const latestResult = session?.latest_result && typeof session.latest_result === "object" ? session.latest_result : {};
  const trackingState =
    session?.state?.capabilities && typeof session.state.capabilities === "object"
      ? session.state.capabilities["tracking-init"] || {}
      : {};
  const trackingMemory = readJson(trackingMemoryFile(sessionId), {});
  const status = trackingStatus(latestResult, trackingState, streamStatus);
  const displayFrame = resolveDisplayFrame(latestResult, trackingState, recentFrames);
  const latestFrame = displayFrame || (recentFrames.length ? recentFrames[recentFrames.length - 1] : perceptionSnapshot?.latest_frame || null);
  const imagePath = resolveProjectFile(String(displayFrame?.image_path || latestFrame?.image_path || "").trim());

  return {
    kind: "agent_viewer_state",
    available: true,
    session_id: sessionId,
    updated_at: session.updated_at,
    agent: {
      latest_result: Object.keys(latestResult).length ? latestResult : null,
      conversation_history: enrichedConversationHistory(session),
      turn_history: Array.isArray(session.result_history) ? session.result_history : [],
    },
    observation: {
      latest_frame: latestFrame,
      stream_status: streamStatus.status,
      detection_count: Array.isArray(latestFrame?.detections) ? latestFrame.detections.length : 0,
    },
    modules: {
      "tracking-init": {
        enabled: true,
        target_id: trackingState?.latest_target_id ?? null,
        pending_question: trackingState?.pending_question || "",
        lifecycle_status: trackingState?.lifecycle_status || "",
        status_kind: status.kind,
        status_label: status.label,
        current_memory: trackingMemoryDisplayText(trackingMemory),
        memory_history: [],
        display_frame:
          displayFrame && imagePath && fs.existsSync(imagePath)
            ? {
                ...displayFrame,
                rendered_image_path: "/viewer-frame.jpg",
              }
            : displayFrame,
      },
    },
    summary: {
      primary_module: "tracking-init",
      target_id: trackingState?.latest_target_id ?? null,
      pending_question: trackingState?.pending_question || "",
      status_kind: status.kind,
      status_label: status.label,
      stream_status: streamStatus.status,
      detection_count: Array.isArray(latestFrame?.detections) ? latestFrame.detections.length : 0,
      frame_id: latestFrame?.frame_id || null,
    },
  };
}

function registerViewerSnapshotRoutes(middlewares) {
  middlewares.use("/viewer-state.json", (_req, res) => {
    const payload = buildViewerState();
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Cache-Control", "no-store");
    res.end(JSON.stringify(payload, null, 2));
  });

  middlewares.use("/viewer-frame.jpg", (_req, res) => {
    const payload = buildViewerState();
    const displayFrame =
      payload?.modules?.["tracking-init"]?.display_frame || payload?.observation?.latest_frame || null;
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
