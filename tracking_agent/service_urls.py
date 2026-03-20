from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_base_url(base_url: str, *, default_scheme: str = "http") -> str:
    cleaned = str(base_url).strip()
    if not cleaned:
        raise ValueError("base_url must not be empty")

    if "://" not in cleaned:
        cleaned = f"{default_scheme}://{cleaned}"

    parsed = urlsplit(cleaned)
    if not parsed.netloc:
        raise ValueError(f"base_url must include a host: {base_url!r}")

    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, normalized_path, "", ""))


def join_url_path(base_url: str, path: str) -> str:
    normalized_base = normalize_base_url(base_url)
    parsed = urlsplit(normalized_base)
    normalized_suffix = "/" + path.lstrip("/")
    combined_path = f"{parsed.path}{normalized_suffix}" if parsed.path else normalized_suffix
    return urlunsplit((parsed.scheme, parsed.netloc, combined_path, "", ""))


def build_backend_service_url(base_url: str, *, channel: str) -> str:
    normalized_base = normalize_base_url(base_url)
    parsed = urlsplit(normalized_base)
    websocket = channel in {
        "robot_agent",
        "robot_ingest",
        "session_events",
    }

    if websocket:
        scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    else:
        scheme = "https" if parsed.scheme in {"https", "wss"} else "http"

    channel_paths = {
        "robot_agent": "/ws/robot-agent",
        "robot_ingest": "/ws/robot-ingest",
        "session_events": "/ws/session-events",
        "robot_http_ingest": "/api/v1/robot/ingest",
    }
    try:
        suffix = channel_paths[channel]
    except KeyError as exc:
        raise ValueError(f"Unsupported backend channel: {channel}") from exc

    combined_path = f"{parsed.path}{suffix}" if parsed.path else suffix
    return urlunsplit((scheme, parsed.netloc, combined_path, "", ""))
