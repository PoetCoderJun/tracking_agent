from tracking_agent.service_urls import build_backend_service_url, join_url_path, normalize_base_url


def test_normalize_base_url_accepts_host_without_scheme() -> None:
    assert normalize_base_url("10.0.0.8:8001") == "http://10.0.0.8:8001"


def test_build_backend_service_url_converts_to_websocket_endpoint() -> None:
    assert (
        build_backend_service_url("https://tracking.example.com/base", channel="robot_agent")
        == "wss://tracking.example.com/base/ws/robot-agent"
    )


def test_join_url_path_preserves_base_path() -> None:
    assert (
        join_url_path("https://tracking.example.com/base", "/api/v1/sessions/sess_001")
        == "https://tracking.example.com/base/api/v1/sessions/sess_001"
    )
