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

function DetectionOverlay({ frame, latestResult, imageSize }) {
  if (!frame || !imageSize.width || !imageSize.height) {
    return null;
  }

  const found = Boolean(latestResult?.found);
  const bbox = Array.isArray(latestResult?.bbox) ? latestResult.bbox : null;
  const targetId = latestResult?.target_id ?? null;

  if (!found || bbox === null) {
    return null;
  }

  const [x1, y1, x2, y2] = bbox;
  const viewBox = `0 0 ${imageSize.width} ${imageSize.height}`;

  return (
    <svg className="overlay" viewBox={viewBox} preserveAspectRatio="none">
      <g>
        <rect
          x={x1}
          y={y1}
          width={Math.max(1, x2 - x1)}
          height={Math.max(1, y2 - y1)}
          className="bbox bbox-target"
        />
        <text x={x1 + 6} y={Math.max(18, y1 - 8)} className="bbox-label bbox-label-target">
          {targetId === null ? "TARGET" : `TARGET ${targetId}`}
        </text>
      </g>
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
        <strong>Frame</strong> {entry.frame_id || "n/a"} | <strong>Target ID</strong>{" "}
        {entry.target_id ?? "n/a"}
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
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [autoFollowLatest, setAutoFollowLatest] = useState(true);
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
        setSessions(nextSessions);

        const selectedStillExists = nextSessions.some(
          (session) => session.session_id === selectedSessionId
        );
        const nextSelectedSessionId = nextSessions.length === 0
          ? ""
          : (autoFollowLatest || !selectedSessionId || !selectedStillExists)
            ? nextSessions[0].session_id
            : selectedSessionId;

        if (nextSelectedSessionId !== selectedSessionId) {
          setSelectedSessionId(nextSelectedSessionId);
        }

        if (!nextSelectedSessionId) {
          if (!cancelled) {
            setState(null);
            setError("");
          }
          return;
        }

        const stateResp = await fetch(
          `/api/v1/sessions/${nextSelectedSessionId}/frontend-state`,
          NO_STORE_FETCH_OPTIONS
        );
        if (!stateResp.ok) {
          throw new Error(`Failed to load session ${nextSelectedSessionId}`);
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
  }, [autoFollowLatest, refreshToken, selectedSessionId]);

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
    if (!selectedSessionId || isClearing) {
      return;
    }
    const confirmed = window.confirm(`确认清空会话 ${selectedSessionId} 吗？`);
    if (!confirmed) {
      return;
    }

    setIsClearing(true);
    try {
      const clearResp = await fetch(`/api/v1/sessions/${selectedSessionId}/clear`, {
        method: "POST"
      });
      if (!clearResp.ok) {
        throw new Error(`Failed to clear session ${selectedSessionId}`);
      }
      const clearedState = await clearResp.json();
      setState(clearedState);
      setError("");

      const sessionsResp = await fetch("/api/v1/sessions", NO_STORE_FETCH_OPTIONS);
      if (!sessionsResp.ok) {
        throw new Error("Failed to refresh sessions");
      }
      const sessionsPayload = await sessionsResp.json();
      setSessions(sessionsPayload.sessions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsClearing(false);
    }
  }

  const sessionOptions = sessions.map(s => ({
    value: s.session_id,
    label: s.device_id || s.session_id.slice(-12)
  }));

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

          <div className="session-selector">
            <select
              value={selectedSessionId}
              onChange={(e) => {
                setSelectedSessionId(e.target.value);
                setAutoFollowLatest(false);
              }}
            >
              {sessionOptions.length === 0 && (
                <option value="">No sessions</option>
              )}
              {sessionOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <button
              className="icon-btn"
              type="button"
              disabled={!selectedSessionId || isClearing}
              onClick={handleClearSession}
              title="清空会话"
            >
              {isClearing ? "⋯" : "↺"}
            </button>
          </div>

          <div className="brand-summary">
            <span className={health === "online" ? "health-chip health-online" : "health-chip health-offline"}>
              {health}
            </span>
            <span className="summary-chip">
              {autoFollowLatest ? "Auto follow" : "Manual view"}
            </span>
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
            <MetricTile label="Target" value={state?.latest_target_id ?? "—"} accent={activeStatus.tone === "good"} />
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
                  <div className="empty-state">No agent history yet.</div>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
