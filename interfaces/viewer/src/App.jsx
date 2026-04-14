import React, { useEffect, useMemo, useRef, useState } from "react";

const VIEWER_STATE_URL = "/viewer-state.json";
const VIEWER_FRAME_URL = "/viewer-frame.jpg";
const POLL_INTERVAL_MS = 1000;

function formatTime(value) {
  if (!value) {
    return "未同步";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "未同步";
  }
  return parsed.toLocaleTimeString();
}

function formatBoundingBoxIdValue(rawId) {
  return rawId === null || rawId === undefined || rawId === "" ? "未绑定" : String(rawId);
}

function normalizedTrackId(rawId) {
  return rawId === null || rawId === undefined || rawId === "" ? "" : String(rawId);
}

function syncStateLabel(syncState) {
  if (syncState === "ready") {
    return "已同步";
  }
  if (syncState === "error") {
    return "读取失败";
  }
  return "读取中";
}

function deriveViewerStatus(viewerState, syncState) {
  const trackingModule = viewerState?.modules?.["tracking-init"] || {};
  const summaryStatusLabel = viewerState?.summary?.status_label;
  const summaryStatusKind = viewerState?.summary?.status_kind;
  if (syncState === "error") {
    return {
      kind: "disconnected",
      label: "读取失败",
      badgeClass: "status-badge-warn",
    };
  }
  if (syncState === "loading") {
    return {
      kind: "connecting",
      label: "读取中",
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

  const latestResult = viewerState?.agent?.latest_result || {};
  const action =
    latestResult?.robot_response?.action || latestResult?.decision || latestResult?.behavior || "";
  const hasPendingQuestion = Boolean(trackingModule?.pending_question || viewerState?.summary?.pending_question);

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
  const debugText = entry?.debug ? JSON.stringify(entry.debug, null, 2) : "";
  return (
    <article className="list-entry">
      <div className="entry-head">
        <span className={`entry-role entry-role-${role}`}>
          {role === "assistant" ? "Agent" : "用户"}
        </span>
        <span className="entry-time">{formatTime(entry.timestamp)}</span>
      </div>
      <div className="entry-body">{entry.text || "空内容"}</div>
      {debugText ? <pre className="entry-debug">{debugText}</pre> : null}
    </article>
  );
}

function DetectionOverlay({ displayFrame, imageSize, targetId }) {
  const detections = Array.isArray(displayFrame?.detections) ? [...displayFrame.detections] : [];
  if ((!detections.length || !detections.some((detection) => normalizedTrackId(detection?.track_id ?? detection?.target_id) === normalizedTrackId(targetId))) && Array.isArray(displayFrame?.bbox) && displayFrame.bbox.length === 4) {
    detections.push({
      track_id: targetId,
      bbox: displayFrame.bbox,
    });
  }
  if (!imageSize.width || !imageSize.height || !detections.length) {
    return null;
  }
  return (
    <svg
      className="overlay"
      viewBox={`0 0 ${imageSize.width} ${imageSize.height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      {detections.map((detection, index) => {
        const bbox = Array.isArray(detection?.bbox) && detection.bbox.length === 4 ? detection.bbox : null;
        if (!bbox) {
          return null;
        }
        const [x1, y1, x2, y2] = bbox;
        const width = Math.max(1, x2 - x1);
        const height = Math.max(1, y2 - y1);
        const detectionId = normalizedTrackId(detection?.track_id ?? detection?.target_id);
        const isTarget = detectionId && detectionId === normalizedTrackId(targetId);
        const label = detectionId ? `ID ${detectionId}` : "ID ?";
        const chipWidth = Math.max(52, label.length * 8 + 12);
        const chipHeight = 22;
        const chipY = Math.max(0, y1 - chipHeight - 4);
        return (
          <g key={`${detectionId || "unknown"}-${index}`}>
            <rect
              className={`bbox ${isTarget ? "bbox-target" : "bbox-candidate"}`}
              x={x1}
              y={y1}
              width={width}
              height={height}
              rx="2"
            />
            <rect
              className={`bbox-label-bg ${isTarget ? "bbox-label-bg-target" : "bbox-label-bg-candidate"}`}
              x={x1}
              y={chipY}
              width={chipWidth}
              height={chipHeight}
              rx="8"
            />
            <text
              className={`bbox-label ${isTarget ? "bbox-label-target" : ""}`}
              x={x1 + 8}
              y={chipY + 15}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function App() {
  const [viewerState, setViewerState] = useState(null);
  const [syncState, setSyncState] = useState("loading");
  const [error, setError] = useState("");
  const [lastSyncedAt, setLastSyncedAt] = useState(null);
  const [refreshSeed, setRefreshSeed] = useState(0);
  const imageRef = useRef(null);
  const stageHostRef = useRef(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [stageHostSize, setStageHostSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    let disposed = false;
    let timerId = null;

    async function pollSnapshot() {
      if (disposed) {
        return;
      }
      setSyncState((current) => (current === "ready" ? current : "loading"));
      try {
        const response = await window.fetch(`${VIEWER_STATE_URL}?t=${Date.now()}&r=${refreshSeed}`, {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`读取 viewer 快照失败：${response.status}`);
        }
        const payload = await response.json();
        if (disposed) {
          return;
        }
        setViewerState(payload);
        setSyncState("ready");
        setError("");
        setLastSyncedAt(new Date());
      } catch (fetchError) {
        if (disposed) {
          return;
        }
        setSyncState("error");
        setError(fetchError instanceof Error ? fetchError.message : "无法读取本地 viewer 快照。");
      } finally {
        if (!disposed) {
          timerId = window.setTimeout(pollSnapshot, POLL_INTERVAL_MS);
        }
      }
    }

    pollSnapshot();
    return () => {
      disposed = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
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
  }, [viewerState?.summary?.frame_id, viewerState?.updated_at]);

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

  const displayFrame = viewerState?.modules?.["tracking-init"]?.display_frame || viewerState?.observation?.latest_frame || null;
  const displayImageUrl =
    displayFrame?.rendered_image_path && viewerState?.updated_at
      ? `${VIEWER_FRAME_URL}?v=${encodeURIComponent(
          `${displayFrame.frame_id || "frame"}-${viewerState.updated_at}`,
        )}`
      : "";
  const viewerStatus = deriveViewerStatus(viewerState, syncState);
  const memoryHistory = [...(viewerState?.modules?.["tracking-init"]?.memory_history || [])].reverse();
  const conversationHistory = [...(viewerState?.agent?.conversation_history || [])].reverse();
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
          <span
            className={`connection-chip connection-chip-${
              syncState === "ready" ? "connected" : syncState === "error" ? "disconnected" : "connecting"
            }`}
          >
            {syncStateLabel(syncState)}
          </span>
          <span className="meta-chip">
            {viewerState?.session_id ? `active ${viewerState.session_id}` : "等待 active session"}
          </span>
          <span className="meta-chip">{lastSyncedAt ? `同步 ${formatTime(lastSyncedAt)}` : "等待快照"}</span>
          <button type="button" className="refresh-button" onClick={() => setRefreshSeed((value) => value + 1)}>
            立即刷新
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
              {displayImageUrl ? (
                <>
                  <img
                    ref={imageRef}
                    className="stage-image"
                    src={displayImageUrl}
                    alt={`当前结果帧 ${displayFrame?.frame_id || ""}`}
                  />
                  <DetectionOverlay
                    displayFrame={displayFrame}
                    imageSize={imageSize}
                    targetId={viewerState?.summary?.target_id}
                  />
                  <div className="stage-note">
                    <strong>{viewerStatus.label}</strong>
                    <span>当前显示的是持久化真相中的画面，边框由 viewer 根据落盘检测结果实时叠加。</span>
                  </div>
                </>
              ) : (
                <div className="empty-stage">
                  <strong>等待画面</strong>
                  <span>viewer 会轮询 session、perception 和 tracking memory 真相文件；当前还没有可显示的画面。</span>
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
              <pre className="memory-block">
                {viewerState?.modules?.["tracking-init"]?.current_memory || "当前还没有 tracking memory。"}
              </pre>
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
                <div className="empty-inline">当前只读取最新 tracking memory，不再维护独立的 viewer 历史镜像。</div>
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
