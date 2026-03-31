import React, { useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_WS_URL = import.meta.env.VITE_TRACKING_VIEWER_WS_URL || "ws://127.0.0.1:8765";
const RECONNECT_DELAY_MS = 2000;
const HISTORY_STORAGE_PREFIX = "tracking-viewer-history:";

function formatTime(value) {
  if (!value) {
    return "未连接";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "未连接";
  }
  return parsed.toLocaleTimeString();
}

function formatBoundingBoxIdValue(rawId) {
  return rawId === null || rawId === undefined || rawId === "" ? "未绑定" : String(rawId);
}

function deriveViewerStatus(viewerState, connectionState) {
  const summaryStatusLabel = viewerState?.summary?.status_label;
  const summaryStatusKind = viewerState?.summary?.status_kind;
  if (connectionState === "disconnected") {
    return {
      kind: "disconnected",
      label: "连接断开",
      badgeClass: "status-badge-warn",
    };
  }
  if (connectionState === "connecting") {
    return {
      kind: "connecting",
      label: "连接中",
      badgeClass: "status-badge-neutral",
    };
  }
  if (!viewerState?.available) {
    return {
      kind: "idle",
      label: "等待会话",
      badgeClass: "status-badge-neutral",
    };
  }
  if (summaryStatusKind === "completed" || viewerState?.summary?.stream_status === "completed") {
    return {
      kind: "completed",
      label: summaryStatusLabel || "视频结束",
      badgeClass: "status-badge-neutral",
    };
  }

  if (summaryStatusKind === "tracking") {
    return {
      kind: "tracking",
      label: summaryStatusLabel || "跟踪中",
      badgeClass: "status-badge-good",
    };
  }
  if (summaryStatusKind === "seeking") {
    return {
      kind: "waiting",
      label: summaryStatusLabel || "寻找中",
      badgeClass: "status-badge-warn",
    };
  }

  const latestResult = viewerState?.latest_result || {};
  const action =
    latestResult?.robot_response?.action || latestResult?.decision || latestResult?.behavior || "";
  const hasPendingQuestion = Boolean(viewerState?.summary?.pending_question);

  if (hasPendingQuestion) {
    return {
      kind: "clarify",
      label: "寻找中",
      badgeClass: "status-badge-warn",
    };
  }
  if (action === "wait") {
    return {
      kind: "waiting",
      label: "寻找中",
      badgeClass: "status-badge-warn",
    };
  }
  if (action === "track" || latestResult?.behavior === "init" || latestResult?.behavior === "track") {
    return {
      kind: "tracking",
      label: "跟踪中",
      badgeClass: "status-badge-good",
    };
  }
  return {
    kind: "idle",
      label: "等待状态",
      badgeClass: "status-badge-neutral",
    };
}

function DetectionOverlay({ displayFrame, imageSize }) {
  if (!displayFrame || !imageSize.width || !imageSize.height) {
    return null;
  }

  const targetId = displayFrame.target_id;
  const detections = Array.isArray(displayFrame?.detections) ? displayFrame.detections : [];
  const bbox =
    Array.isArray(displayFrame?.bbox) && displayFrame.bbox.length === 4
      ? displayFrame.bbox
      : detections.find((detection) => {
          const detectionTrackId = detection?.track_id ?? detection?.target_id ?? null;
          return targetId !== null && detectionTrackId !== null && String(detectionTrackId) === String(targetId);
        })?.bbox ?? null;
  const viewBox = `0 0 ${imageSize.width} ${imageSize.height}`;

  return (
    <svg className="overlay" viewBox={viewBox} preserveAspectRatio="none">
      {detections.map((detection) => {
        const detectionBbox = Array.isArray(detection?.bbox) ? detection.bbox : null;
        const detectionTrackId = detection.track_id ?? detection.target_id ?? null;
        if (detectionBbox === null) {
          return null;
        }
        if (
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
            <rect
              x={x1}
              y={Math.max(2, y1 - 24)}
              width={34}
              height={20}
              rx={8}
              className="bbox-label-bg bbox-label-bg-candidate"
            />
            <text x={x1 + 6} y={Math.max(18, y1 - 8)} className="bbox-label">
              {String(detectionTrackId ?? "?")}
            </text>
          </g>
        );
      })}
      {bbox ? (
        <g>
          <rect
            x={bbox[0]}
            y={bbox[1]}
            width={Math.max(1, bbox[2] - bbox[0])}
            height={Math.max(1, bbox[3] - bbox[1])}
            className="bbox bbox-target"
          />
          <rect
            x={bbox[0]}
            y={Math.max(2, bbox[1] - 28)}
            width={42}
            height={22}
            rx={8}
            className="bbox-label-bg bbox-label-bg-target"
          />
          <text
            x={bbox[0] + 7}
            y={Math.max(18, bbox[1] - 10)}
            className="bbox-label bbox-label-target"
          >
            {String(targetId ?? "?")}
          </text>
        </g>
      ) : null}
    </svg>
  );
}

function MemoryEntry({ entry }) {
  return (
    <article className="list-entry">
      <div className="entry-head">
        <span className="entry-chip">{entry.behavior || "memory"}</span>
        <span className="entry-time">{formatTime(entry.updated_at)}</span>
      </div>
      <div className="entry-subline">
        帧 {entry.frame_id || "未记录"} · 目标 {formatBoundingBoxIdValue(entry.target_id)}
      </div>
      <div className="entry-body">{entry.memory || "无记忆内容"}</div>
    </article>
  );
}

function ConversationEntry({ entry }) {
  const role = entry.role === "assistant" ? "assistant" : "user";
  return (
    <article className="list-entry">
      <div className="entry-head">
        <span className={`entry-role entry-role-${role}`}>
          {role === "assistant" ? "Agent" : "用户"}
        </span>
        <span className="entry-time">{formatTime(entry.timestamp)}</span>
      </div>
      <div className="entry-body">{entry.text || "空内容"}</div>
    </article>
  );
}

function historyStorageKey(sessionId) {
  return `${HISTORY_STORAGE_PREFIX}${sessionId}`;
}

function loadStoredHistory(sessionId) {
  if (!sessionId) {
    return { conversationHistory: [], memoryHistory: [] };
  }
  try {
    const raw = window.localStorage.getItem(historyStorageKey(sessionId));
    if (!raw) {
      return { conversationHistory: [], memoryHistory: [] };
    }
    const parsed = JSON.parse(raw);
    return {
      conversationHistory: Array.isArray(parsed?.conversationHistory) ? parsed.conversationHistory : [],
      memoryHistory: Array.isArray(parsed?.memoryHistory) ? parsed.memoryHistory : [],
    };
  } catch {
    return { conversationHistory: [], memoryHistory: [] };
  }
}

function mergeConversationHistory(existing, incoming) {
  const merged = [...existing];
  const seen = new Set(
    merged.map((entry) => `${entry.timestamp || ""}|${entry.role || ""}|${entry.text || ""}`),
  );
  for (const entry of incoming || []) {
    const key = `${entry?.timestamp || ""}|${entry?.role || ""}|${entry?.text || ""}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    merged.push(entry);
  }
  return merged;
}

function appendMemorySnapshot(existing, viewerState) {
  const memory = String(viewerState?.current_memory || "").trim();
  if (!memory) {
    return existing;
  }
  const nextEntry = {
    updated_at: viewerState?.updated_at || "",
    frame_id: viewerState?.summary?.frame_id || "",
    target_id: viewerState?.summary?.target_id ?? null,
    behavior: viewerState?.latest_result?.behavior || "memory",
    memory,
  };
  const key = `${nextEntry.updated_at}|${nextEntry.frame_id}|${nextEntry.memory}`;
  const last = existing[existing.length - 1];
  if (last) {
    const lastKey = `${last.updated_at || ""}|${last.frame_id || ""}|${last.memory || ""}`;
    if (lastKey === key) {
      return existing;
    }
  }
  return [...existing, nextEntry];
}

export default function App() {
  const [viewerState, setViewerState] = useState(null);
  const [connectionState, setConnectionState] = useState("connecting");
  const [error, setError] = useState("");
  const [lastMessageAt, setLastMessageAt] = useState(null);
  const [refreshSeed, setRefreshSeed] = useState(0);
  const imageRef = useRef(null);
  const stageHostRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const lastSessionIdRef = useRef("");
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [stageHostSize, setStageHostSize] = useState({ width: 0, height: 0 });
  const [conversationLog, setConversationLog] = useState([]);
  const [memoryLog, setMemoryLog] = useState([]);
  const [lastGoodDisplayFrame, setLastGoodDisplayFrame] = useState(null);
  const sessionId = viewerState?.session_id || "";

  useEffect(() => {
    if (!sessionId) {
      setConversationLog([]);
      setMemoryLog([]);
      return;
    }
    const stored = loadStoredHistory(sessionId);
    setConversationLog(stored.conversationHistory);
    setMemoryLog(stored.memoryHistory);
  }, [sessionId]);

  useEffect(() => {
    if (sessionId === lastSessionIdRef.current) {
      return;
    }
    lastSessionIdRef.current = sessionId;
    setLastGoodDisplayFrame(null);
    setImageSize({ width: 0, height: 0 });
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || !viewerState) {
      return;
    }
    setConversationLog((current) =>
      mergeConversationHistory(current, viewerState?.conversation_history || []),
    );
    setMemoryLog((current) => appendMemorySnapshot(current, viewerState));
  }, [sessionId, viewerState]);

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    window.localStorage.setItem(
      historyStorageKey(sessionId),
      JSON.stringify({
        conversationHistory: conversationLog,
        memoryHistory: memoryLog,
      }),
    );
  }, [sessionId, conversationLog, memoryLog]);

  useEffect(() => {
    let disposed = false;
    let socket = null;

    function connect() {
      if (disposed) {
        return;
      }

      setConnectionState("connecting");
      socket = new window.WebSocket(DEFAULT_WS_URL);

      socket.addEventListener("open", () => {
        if (disposed) {
          return;
        }
        setConnectionState("connected");
        setError("");
      });

      socket.addEventListener("message", (event) => {
        if (disposed) {
          return;
        }
        try {
          const payload = JSON.parse(event.data);
          setViewerState(payload);
          setLastMessageAt(new Date());
          setError("");
        } catch (parseError) {
          setError(parseError instanceof Error ? parseError.message : "无法解析 websocket 数据。");
        }
      });

      socket.addEventListener("error", () => {
        if (disposed) {
          return;
        }
        setError("Viewer websocket 已断开。");
      });

      socket.addEventListener("close", () => {
        if (disposed) {
          return;
        }
        setConnectionState("disconnected");
        reconnectTimerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
      });
    }

    connect();
    return () => {
      disposed = true;
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (socket) {
        socket.close();
      }
    };
  }, [refreshSeed]);

  useEffect(() => {
    const image = imageRef.current;
    if (!image) {
      return undefined;
    }

    function updateSize() {
      setImageSize({
        width: image.naturalWidth,
        height: image.naturalHeight,
      });
    }

    image.addEventListener("load", updateSize);
    updateSize();
    return () => {
      image.removeEventListener("load", updateSize);
    };
  }, [viewerState?.display_frame?.frame_id, viewerState?.display_frame?.image_data_url]);

  useEffect(() => {
    const nextDisplayFrame = viewerState?.display_frame || null;
    if (!nextDisplayFrame?.image_data_url) {
      return;
    }
    setLastGoodDisplayFrame((current) => {
      if (
        current?.frame_id === nextDisplayFrame.frame_id &&
        current?.image_data_url === nextDisplayFrame.image_data_url
      ) {
        return current;
      }
      return nextDisplayFrame;
    });
  }, [viewerState?.display_frame]);

  useEffect(() => {
    const host = stageHostRef.current;
    if (!host) {
      return undefined;
    }

    function updateHostSize() {
      setStageHostSize({
        width: host.clientWidth,
        height: host.clientHeight,
      });
    }

    updateHostSize();
    const observer = new window.ResizeObserver(updateHostSize);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  const liveDisplayFrame = viewerState?.display_frame || null;
  const displayFrame = liveDisplayFrame?.image_data_url ? liveDisplayFrame : lastGoodDisplayFrame;
  const showingFallbackFrame =
    !liveDisplayFrame?.image_data_url && Boolean(lastGoodDisplayFrame?.image_data_url);
  const viewerStatus = deriveViewerStatus(viewerState, connectionState);
  const memoryHistory = [...memoryLog].reverse();
  const conversationHistory = [...conversationLog].reverse();
  const viewerStageStyle = useMemo(() => {
    if (!imageSize.width || !imageSize.height || !stageHostSize.width || !stageHostSize.height) {
      return null;
    }
    const imageAspectRatio = imageSize.width / imageSize.height;
    let width = stageHostSize.width;
    let height = width / imageAspectRatio;
    if (height > stageHostSize.height) {
      height = stageHostSize.height;
      width = height * imageAspectRatio;
    }
    return {
      width: `${Math.floor(width)}px`,
      height: `${Math.floor(height)}px`,
    };
  }, [imageSize.height, imageSize.width, stageHostSize.height, stageHostSize.width]);

  return (
    <div className="viewer-shell">
      <header className="topbar surface">
        <div className="topbar-meta">
          <span className={`connection-chip connection-chip-${connectionState}`}>{connectionState}</span>
          <span className="meta-chip">
            {viewerState?.session_id ? `active ${viewerState.session_id}` : "等待 active session"}
          </span>
          <span className="meta-chip">{lastMessageAt ? `收到 ${formatTime(lastMessageAt)}` : "等待消息"}</span>
          <button type="button" className="refresh-button" onClick={() => setRefreshSeed((value) => value + 1)}>
            重新连接
          </button>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <main className="main-grid">
        <section className="surface stage-surface">
          <div className="section-head section-head-tight stage-head">
            <div>
              <div className="eyebrow">Stage</div>
              <h2>当前跟踪画面</h2>
            </div>
            <div className="meta-strip">
              <span className={`status-badge ${viewerStatus.badgeClass}`}>{viewerStatus.label}</span>
              <span className="meta-chip">
                帧 {displayFrame?.frame_id || viewerState?.summary?.frame_id || "未收到"}
              </span>
              <span className="meta-chip">
                目标 {formatBoundingBoxIdValue(viewerState?.summary?.target_id)}
              </span>
            </div>
          </div>
          <div className="stage-host" ref={stageHostRef}>
            <div
              className={viewerStageStyle ? "stage-canvas stage-canvas-fitted" : "stage-canvas"}
              style={viewerStageStyle || undefined}
            >
              {displayFrame?.image_data_url ? (
                <>
                  <img
                    ref={imageRef}
                    className="stage-image"
                    src={displayFrame.image_data_url}
                    alt={`当前结果帧 ${displayFrame.frame_id || ""}`}
                  />
                  <DetectionOverlay displayFrame={displayFrame} imageSize={imageSize} />
                  <div className="stage-note">
                    <strong>{viewerStatus.label}</strong>
                    {showingFallbackFrame ? (
                      <span className="stage-note-inline">
                        当前显示的是上一张可靠画面：{lastGoodDisplayFrame?.frame_id || "未知帧"}
                      </span>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="empty-stage">
                  <strong>等待画面</strong>
                  <span>启动 tracking perception 后会自动创建随机 active session，viewer 会只跟随这一条会话。</span>
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="surface memory-surface">
          <div className="section-head section-head-tight">
            <div>
              <div className="eyebrow">Memory</div>
              <h2>当前与历史记忆</h2>
            </div>
            <span className="meta-chip">
              目标 {formatBoundingBoxIdValue(viewerState?.summary?.target_id)}
            </span>
          </div>

          <div className="memory-scroll">
            <div className="current-memory-card">
              <div className="card-label">当前记忆</div>
              <pre className="memory-block">{viewerState?.current_memory || "当前还没有 tracking memory。"}</pre>
            </div>

            {viewerState?.summary?.pending_question ? (
              <div className="warning-note">
                <strong>待用户澄清</strong>
                <p>{viewerState.summary.pending_question}</p>
              </div>
            ) : null}

            <div className="list-head">
              <strong>历史记忆</strong>
              <span>{memoryHistory.length}</span>
            </div>
            <div className="entry-list entry-list-static">
              {memoryHistory.length ? (
                memoryHistory.map((entry, index) => (
                  <MemoryEntry key={`${entry.updated_at || "memory"}-${index}`} entry={entry} />
                ))
              ) : (
                <div className="empty-inline">还没有历史 memory。</div>
              )}
            </div>
          </div>
        </section>

        <section className="surface dialogue-surface">
          <div className="list-head">
            <strong>对话历史</strong>
            <span>{conversationHistory.length}</span>
          </div>
          <div className="entry-list">
            {conversationHistory.length ? (
              conversationHistory.map((entry, index) => (
                <ConversationEntry key={`${entry.timestamp || "turn"}-${index}`} entry={entry} />
              ))
            ) : (
              <div className="empty-inline">还没有对话历史。</div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
