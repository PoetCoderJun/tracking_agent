import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function normalizeBaseUrl(value, defaultProtocol) {
  const raw = String(value ?? "").trim();
  if (!raw) {
    return "";
  }
  if (/^[a-z]+:\/\//i.test(raw)) {
    return raw.replace(/\/+$/, "");
  }
  return `${defaultProtocol}://${raw}`.replace(/\/+$/, "");
}

function websocketTargetFromHttpTarget(target) {
  if (!target) {
    return "";
  }
  return target.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const httpTarget = normalizeBaseUrl(env.VITE_BACKEND_PROXY_TARGET || "http://127.0.0.1:8001", "http");
  const wsTarget = normalizeBaseUrl(
    env.VITE_BACKEND_PROXY_WS_TARGET || websocketTargetFromHttpTarget(httpTarget),
    "ws"
  );
  const port = Number(env.VITE_DEV_PORT || 5173);

  return {
    plugins: [react()],
    server: {
      port,
      proxy: {
        "/api": httpTarget,
        "/healthz": httpTarget,
        "/ws": {
          target: wsTarget,
          ws: true
        }
      }
    }
  };
});
