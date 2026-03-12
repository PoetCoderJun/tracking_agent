import React, { useEffect, useMemo, useRef, useState } from "react";

const NO_STORE_FETCH_OPTIONS = { cache: "no-store" };
const WS_RECONNECT_DELAY_MS = 2000;

function getFrontendUpdatesSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/frontend-updates`;
}

function getTrackingStatus(latestResult) {
  if (!latestResult) {
    return { label: "idle", tone: "neutral" };
  }
  if (latestResult.behavior === "error") {
    return { label: "error", tone: "warn" };
  }
  if (latestResult.needs_clarification) {
    return { label: "clarify", tone: "warn" };
  }
  if (latestResult.found) {
    return { label: "tracking", tone: "good" };
  }
  return { label: "waiting", tone: "neutral" };
}

function StatusPill({ latestResult }) {
  const status = getTrackingStatus(latestResult);
  return <span className={`pill pill-${status.tone}`}>{status.label}</span>;
}

function MetricTile({ label, value, accent = false }) {
  return (
    <div className={accent ? "metric-tile metric-tile-accent" : "metric-tile"}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
    </div>
  );
}

function getRawBoundingBoxId(source) {
  if (!source || typeof source !== "object") {
    return null;
  }

  return source.bounding_box_id ?? source.bbox_id ?? source.box_id ?? source.track_id ?? source.target_id ?? null;
}

function formatBoundingBoxIdValue(rawId) {
  return rawId === null || rawId === undefined || rawId === "" ? "?" : String(rawId);
}

function DetectionOverlay({ frame, latestResult, imageSize }) {
  if (!frame || !imageSize.width || !imageSize.height) {
    return null;
  }

  const detections = Array.isArray(frame.detections) ? frame.detections : [];
  const found = Boolean(latestResult?.found);
  const bbox = Array.isArray(latestResult?.bbox) ? latestResult.bbox : null;
  const targetId = getRawBoundingBoxId(latestResult);
  const viewBox = `0 0 ${imageSize.width} ${imageSize.height}`;
  const hasTargetBox = found && bbox !== null;

  if (!detections.length && !hasTargetBox) {
    return null;
  }

  return (
    <svg className="overlay" viewBox={viewBox} preserveAspectRatio="none">
      {detections.map((detection) => {
        const detectionBbox = Array.isArray(detection?.bbox) ? detection.bbox : null;
        if (detectionBbox === null) {
          return null;
        }
        const detectionTrackId = getRawBoundingBoxId(detection);
        if (
          hasTargetBox &&
          targetId !== null &&
          detectionTrackId !== null &&
          String(detectionTrackId) === String(targetId)
        ) {
          return null;
        }
        const [x1, y1, x2, y2] = detectionBbox;
        return (
          <g key={`candidate-${detectionTrackId ?? "unknown"}-${x1}-${y1}-${x2}-${y2}`}>
            <rect
              x={x1}
              y={y1}
              width={Math.max(1, x2 - x1)}
              height={Math.max(1, y2 - y1)}
              className="bbox bbox-candidate"
            />
            <text x={x1 + 6} y={Math.max(18, y1 - 8)} className="bbox-label">
              {formatBoundingBoxIdValue(detectionTrackId)}
            </text>
          </g>
        );
      })}
      {hasTargetBox ? (
        <g>
          <rect
            x={bbox[0]}
            y={bbox[1]}
            width={Math.max(1, bbox[2] - bbox[0])}
            height={Math.max(1, bbox[3] - bbox[1])}
            className="bbox bbox-target"
          />
          <text
            x={bbox[0] + 6}
            y={Math.max(18, bbox[1] - 8)}
            className="bbox-label bbox-label-target"
          >
            {formatBoundingBoxIdValue(targetId)}
          </text>
        </g>
      ) : null}
    </svg>
  );
}

function HistoryEntry({ entry }) {
  return (
    <article className="history-entry">
      <div className="history-head">
        <div className="history-meta">
          <span className="history-time">
            {entry.updated_at ? new Date(entry.updated_at).toLocaleString() : "n/a"}
          </span>
          <span className="history-mode">{entry.behavior || entry.mode || "track"}</span>
        </div>
        <StatusPill latestResult={entry} />
      </div>
      <div className="history-line">
        <strong>Frame</strong> {entry.frame_id || "n/a"} | <strong>Bounding Box ID</strong>{" "}
        {formatBoundingBoxIdValue(getRawBoundingBoxId(entry))}
      </div>
      <div className="history-text">{entry.text || "No agent reply."}</div>
      {entry.memory ? <div className="timeline-memory">{entry.memory}</div> : null}
    </article>
  );
}

function ConversationEntry({ entry }) {
  const roleLabel = entry.role === "assistant" ? "Agent" : "User";

  return (
    <article className="conversation-entry">
      <div className="conversation-head">
        <span className={`conversation-role conversation-role-${entry.role || "user"}`}>{roleLabel}</span>
        <span className="conversation-time">
          {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : "n/a"}
        </span>
      </div>
      <div className="conversation-text">{entry.text || "Empty turn."}</div>
    </article>
  );
}

export default function App() {
  const [activeSession, setActiveSession] = useState(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState("checking");
  const [isClearing, setIsClearing] = useState(false);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const imageRef = useRef(null);
  const viewerHostRef = useRef(null);
  const [viewerHostSize, setViewerHostSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    let cancelled = false;

    async function refreshDashboard() {
      try {
        const healthResp = await fetch("/healthz", NO_STORE_FETCH_OPTIONS);
        if (!healthResp.ok) {
          throw new Error("Backend health check failed");
        }
        if (!cancelled) {
          setHealth("online");
        }

        const sessionsResp = await fetch("/api/v1/sessions", NO_STORE_FETCH_OPTIONS);
        if (!sessionsResp.ok) {
          throw new Error("Failed to load sessions");
        }
        const sessionsPayload = await sessionsResp.json();
        const nextSessions = sessionsPayload.sessions || [];
        if (cancelled) {
          return;
        }
        const nextActiveSession = nextSessions[0] ?? null;
        setActiveSession(nextActiveSession);

        if (!nextActiveSession) {
          if (!cancelled) {
            setState(null);
            setError("");
          }
          return;
        }

        const stateResp = await fetch(
          `/api/v1/sessions/${nextActiveSession.session_id}/frontend-state`,
          NO_STORE_FETCH_OPTIONS
        );
        if (!stateResp.ok) {
          throw new Error(`Failed to load session ${nextActiveSession.session_id}`);
        }
        const statePayload = await stateResp.json();
        if (!cancelled) {
          setState(statePayload);
          setError("");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setHealth("offline");
        }
      }
    }

    refreshDashboard();
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  useEffect(() => {
    let disposed = false;
    let socket = null;
    let reconnectTimer = null;

    function connect() {
      if (disposed) {
        return;
      }

      socket = new window.WebSocket(getFrontendUpdatesSocketUrl());

      socket.addEventListener("open", () => {
        setRefreshToken((value) => value + 1);
      });

      socket.addEventListener("message", (event) => {
        let payload = null;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (payload?.type === "session_update" || payload?.type === "connected") {
          setRefreshToken((value) => value + 1);
        }
      });

      socket.addEventListener("close", () => {
        if (disposed) {
          return;
        }
        reconnectTimer = window.setTimeout(connect, WS_RECONNECT_DELAY_MS);
      });
    }

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (socket) {
        socket.close();
      }
    };
  }, []);

  useEffect(() => {
    const image = imageRef.current;
    if (!image) {
      return;
    }
    function updateSize() {
      setImageSize({
        width: image.naturalWidth,
        height: image.naturalHeight
      });
    }
    image.addEventListener("load", updateSize);
    updateSize();
    return () => {
      image.removeEventListener("load", updateSize);
    };
  }, [state?.latest_frame?.image_url]);

  useEffect(() => {
    const host = viewerHostRef.current;
    if (!host) {
      return;
    }

    function updateHostSize() {
      setViewerHostSize({
        width: host.clientWidth,
        height: host.clientHeight
      });
    }

    updateHostSize();

    if (typeof window.ResizeObserver !== "function") {
      window.addEventListener("resize", updateHostSize);
      return () => {
        window.removeEventListener("resize", updateHostSize);
      };
    }

    const observer = new window.ResizeObserver(() => {
      updateHostSize();
    });
    observer.observe(host);
    return () => {
      observer.disconnect();
    };
  }, []);

  const latestResult = state?.latest_result ?? null;
  const latestFrame = state?.latest_frame ?? null;
  const activeSessionId = state?.session_id || activeSession?.session_id || "";
  const activeSessionLabel = state?.device_id || activeSession?.device_id || "No active session";
  const resultHistory = state?.result_history ?? [];
  const lastUpdate = useMemo(() => {
    if (!state?.updated_at) {
      return "n/a";
    }
    return new Date(state.updated_at).toLocaleString();
  }, [state?.updated_at]);
  const timelineEntries = useMemo(
    () => [...resultHistory].slice(-6).reverse(),
    [resultHistory]
  );
  const conversationEntries = useMemo(
    () => [...(state?.conversation_history ?? [])].slice(-6).reverse(),
    [state?.conversation_history]
  );
  const detectionCount = latestFrame?.detections?.length ?? 0;
  const activeStatus = getTrackingStatus(latestResult);
  const viewerStageStyle = useMemo(() => {
    if (!imageSize.width || !imageSize.height || !viewerHostSize.width || !viewerHostSize.height) {
      return null;
    }

    const imageAspectRatio = imageSize.width / imageSize.height;
    const hostAspectRatio = viewerHostSize.width / viewerHostSize.height;

    if (!Number.isFinite(imageAspectRatio) || !Number.isFinite(hostAspectRatio)) {
      return null;
    }

    let width = viewerHostSize.width;
    let height = width / imageAspectRatio;

    if (height > viewerHostSize.height) {
      height = viewerHostSize.height;
      width = height * imageAspectRatio;
    }

    return {
      width: `${Math.floor(width)}px`,
      height: `${Math.floor(height)}px`
    };
  }, [imageSize.height, imageSize.width, viewerHostSize.height, viewerHostSize.width]);

  async function handleClearSession() {
    if (!activeSessionId || isClearing) {
      return;
    }
    const confirmed = window.confirm(`确认清空当前会话 ${activeSessionId} 吗？`);
    if (!confirmed) {
      return;
    }

    setIsClearing(true);
    try {
      const clearResp = await fetch(`/api/v1/sessions/${activeSessionId}/clear`, {
        method: "POST"
      });
      if (!clearResp.ok) {
        throw new Error(`Failed to clear session ${activeSessionId}`);
      }
      const clearedState = await clearResp.json();
      setState(clearedState);
      setActiveSession((current) => current ? { ...current, ...clearedState } : clearedState);
      setError("");
      setRefreshToken((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsClearing(false);
    }
  }

  return (
    <div className="shell">
      <aside className="left-rail">
        <div className="brand-block">
          <div className="brand-top">
            <div className="brand-copy">
              <span className="eyebrow">Tracking Workspace</span>
              <h1>Session View</h1>
              <p className="brand-description">
                实时查看机器人追踪状态、上下文记忆和对话轨迹。
              </p>
            </div>
            <StatusPill latestResult={latestResult} />
          </div>

          <div className="session-toolbar">
            <div className="session-current">
              <span className="session-current-label">Current session</span>
              <strong>{activeSessionLabel}</strong>
              <span>{activeSessionId || "Waiting for session"}</span>
            </div>
            <button
              className="icon-btn"
              type="button"
              disabled={!activeSessionId || isClearing}
              onClick={handleClearSession}
              title="清空当前会话"
            >
              {isClearing ? "⋯" : "↺"}
            </button>
          </div>

          <div className="brand-summary">
            <span className={health === "online" ? "health-chip health-online" : "health-chip health-offline"}>
              {health}
            </span>
            <span className="summary-chip">Single session</span>
          </div>
        </div>

        <div className="panel context-panel">
          <div className="panel-header">
            <div>
              <span className="eyebrow">Context</span>
              <h2>Current focus</h2>
            </div>
          </div>
          <div className="context-content">
            <div className="context-item">
              <span className="context-label">Target</span>
              <span className="context-value">{state?.target_description || "—"}</span>
            </div>
            <div className="context-item">
              <span className="context-label">Memory</span>
              <span className="context-value">{state?.latest_memory || "—"}</span>
            </div>
            {state?.pending_question || latestResult?.clarification_question ? (
              <div className="context-item context-item-warn">
                <span className="context-label">Question</span>
                <span className="context-value">
                  {state?.pending_question || latestResult?.clarification_question}
                </span>
              </div>
            ) : null}
          </div>
        </div>

        <div className="panel stats-panel">
          <div className="panel-header">
            <div>
              <span className="eyebrow">Stats</span>
              <h2>Live metrics</h2>
            </div>
          </div>
          <div className="stats-grid">
            <MetricTile
              label="Bounding Box ID"
              value={formatBoundingBoxIdValue(
                state?.latest_result ? getRawBoundingBoxId(state.latest_result) : state?.latest_target_id
              )}
              accent={activeStatus.tone === "good"}
            />
            <MetricTile label="Frame" value={latestFrame?.frame_id ?? "—"} />
            <MetricTile label="Detections" value={detectionCount} />
            <MetricTile label="Updated" value={lastUpdate} />
          </div>
        </div>
      </aside>

      <main className="main-stage">
        <section className="viewer-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Live Frame</span>
              <h2>Visual tracking stage</h2>
            </div>
            <div className="section-meta">
              <span>{detectionCount} detections</span>
              <span>{lastUpdate}</span>
            </div>
          </div>
          <div className="viewer-stage-shell">
            <div className="viewer-stage-wrap" ref={viewerHostRef}>
              <div
                className={viewerStageStyle ? "viewer-stage viewer-stage-fitted" : "viewer-stage"}
                style={viewerStageStyle || undefined}
              >
                {latestFrame ? (
                  <>
                    <img
                      key={latestFrame.image_url}
                      ref={imageRef}
                      className="frame-image"
                      src={`${latestFrame.image_url}?t=${encodeURIComponent(state?.updated_at || "")}`}
                      alt={latestFrame.frame_id}
                    />
                    <DetectionOverlay frame={latestFrame} latestResult={latestResult} imageSize={imageSize} />
                  </>
                ) : (
                  <div className="empty-stage">
                    <div className="empty-stage-copy">
                      <strong>Waiting for frame</strong>
                      <span>Robot ingest 开始后，最新画面会出现在这里。</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {error ? <div className="error-banner">{error}</div> : null}
        </section>

        <section className="timeline-panel">
          <div className="timeline-header">
            <div>
              <span className="eyebrow">Activity</span>
              <h2>Recent timeline</h2>
            </div>
          </div>
          <div className="timeline-body">
            <div className="timeline-section">
              <div className="timeline-section-header">
                <span className="timeline-section-title">Dialogue</span>
                <span className="timeline-section-count">{conversationEntries.length}</span>
              </div>
              <div className="conversation-list">
                {conversationEntries.length ? (
                  conversationEntries.map((entry, index) => (
                    <ConversationEntry
                      key={`${entry.timestamp || "turn"}-${index}`}
                      entry={entry}
                    />
                  ))
                ) : (
                  <div className="empty-state">No conversation history yet.</div>
                )}
              </div>
            </div>

            <div className="timeline-section">
              <div className="timeline-section-header">
                <span className="timeline-section-title">Agent turns</span>
                <span className="timeline-section-count">{timelineEntries.length}</span>
              </div>
              <div className="timeline-list">
                {timelineEntries.length ? (
                  timelineEntries.map((entry, index) => (
                    <HistoryEntry key={`${entry.updated_at || "entry"}-${index}`} entry={entry} />
                  ))
                ) : (
                  <div className="empty-state">
                    No agent turns yet. 如果 backend 没配自动 agent，就需要外部 agent 回写
                    <code>/agent-result</code>。
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
