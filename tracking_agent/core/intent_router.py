from __future__ import annotations


def classify_user_intent(text: str, has_active_session: bool) -> str:
    lowered = text.strip().lower()

    replace_markers = ("换一个", "重新初始化", "重新跟踪", "换目标", "replace target")
    if any(marker in lowered for marker in replace_markers):
        return "replace_target" if has_active_session else "initialize_target"

    init_markers = ("跟踪", "track", "找一下", "定位")
    if any(marker in lowered for marker in init_markers) and not has_active_session:
        return "initialize_target"

    whereabouts_markers = ("去哪", "where did", "在哪里", "去哪了")
    if any(marker in lowered for marker in whereabouts_markers):
        return "ask_whereabouts"

    status_markers = ("状态", "还在跟踪", "same target", "why")
    if any(marker in lowered for marker in status_markers):
        return "ask_tracking_status"

    clarify_markers = ("我指的是", "不是", "左边那个", "右边那个", "更高的", "更矮的")
    if any(marker in lowered for marker in clarify_markers):
        return "clarify_target"

    continue_markers = ("继续", "continue")
    if any(marker in lowered for marker in continue_markers):
        return "continue_tracking"

    return "chat"
