from viewer.stream import parse_args


def test_parse_args_viewer_stream(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_viewer_stream.py",
            "--session-id",
            "sess_viewer",
            "--host",
            "0.0.0.0",
            "--port",
            "9001",
        ],
    )

    args = parse_args()

    assert args.session_id == "sess_viewer"
    assert args.host == "0.0.0.0"
    assert args.port == 9001
    assert args.state_root == "./.runtime/agent-runtime"


def test_parse_args_viewer_stream_allows_active_session_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tracking_viewer_stream.py",
        ],
    )

    args = parse_args()

    assert args.session_id is None
    assert args.poll_interval == 1.0
