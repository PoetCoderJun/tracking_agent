from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT_PDF = ROOT / "tracking-agent-embodied-architecture-report.pdf"
PAGE_W = 1240
PAGE_H = 1754
MARGIN = 72

BG = "#f5efe6"
PAPER = "#fffaf3"
PANEL = "#fffdf9"
TEXT = "#1d1b17"
MUTED = "#5d584f"
LINE = "#d9d0c4"
TEAL = "#0d6b63"
TEAL_SOFT = "#e7f4f1"
ORANGE = "#b85b2f"
ORANGE_SOFT = "#f8ebe3"
NAVY = "#1d3557"
NAVY_SOFT = "#e9eef5"
GOLD = "#c18b2f"
SHADOW = "#efe7db"

FONT_REGULAR = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_MONO = "/System/Library/Fonts/Helvetica.ttc"


def load_font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_MONO if mono else (FONT_BOLD if bold else FONT_REGULAR)
    return ImageFont.truetype(path, size=size)


FONT_TINY = load_font(12, bold=True)
FONT_SMALL = load_font(15)
FONT_BODY = load_font(18)
FONT_BODY_BOLD = load_font(18, bold=True)
FONT_H3 = load_font(22, bold=True)
FONT_H2 = load_font(30, bold=True)
FONT_H1 = load_font(54, bold=True)
FONT_METRIC = load_font(30, bold=True)
FONT_MONO_SMALL = load_font(16, mono=True)


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            tentative = current + char
            if not current or text_width(draw, tentative, font) <= max_width:
                current = tentative
                continue
            lines.append(current)
            current = char
        if current:
            lines.append(current)
    return lines or [""]


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 8,
) -> int:
    lines = wrap_text(draw, text, font, max_width)
    line_h = (draw.textbbox((0, 0), "测试Ag", font=font)[3] - draw.textbbox((0, 0), "测试Ag", font=font)[1]) + line_gap
    cursor = y
    for line in lines:
        draw.text((x, cursor), line, font=font, fill=fill)
        cursor += line_h
    return cursor


def rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill: str = PANEL, outline: str = LINE, radius: int = 28) -> None:
    x1, y1, x2, y2 = box
    shadow_box = (x1 + 6, y1 + 8, x2 + 6, y2 + 8)
    draw.rounded_rectangle(shadow_box, radius=radius, fill=SHADOW)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def pill(draw: ImageDraw.ImageDraw, *, x: int, y: int, text: str, fill: str = TEAL_SOFT, ink: str = TEAL) -> int:
    padding_x = 18
    h = 34
    w = text_width(draw, text, FONT_SMALL) + padding_x * 2
    draw.rounded_rectangle((x, y, x + w, y + h), radius=17, fill=fill, outline=LINE, width=1)
    draw.text((x + padding_x, y + 7), text, font=FONT_SMALL, fill=ink)
    return w


def footer(draw: ImageDraw.ImageDraw, page_no: int, total: int) -> None:
    draw.text((MARGIN, PAGE_H - 42), "Tracking Agent Embodied Architecture Report", font=FONT_SMALL, fill=MUTED)
    label = f"{page_no} / {total}"
    draw.text((PAGE_W - MARGIN - text_width(draw, label, FONT_SMALL), PAGE_H - 42), label, font=FONT_SMALL, fill=MUTED)


def create_page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (PAGE_W, PAGE_H), BG)
    draw = ImageDraw.Draw(image)
    draw.ellipse((-120, -70, 240, 280), fill=TEAL_SOFT)
    draw.ellipse((PAGE_W - 280, -90, PAGE_W + 80, 260), fill=ORANGE_SOFT)
    draw.rectangle((0, 0, PAGE_W, PAGE_H), outline=None, fill=None)
    return image, draw


def metric_card(draw: ImageDraw.ImageDraw, *, x: int, y: int, w: int, number: str, label: str) -> None:
    rounded_panel(draw, (x, y, x + w, y + 124), fill=PANEL)
    draw.text((x + 18, y + 20), number, font=FONT_METRIC, fill=TEXT)
    draw.text((x + 18, y + 74), label, font=FONT_SMALL, fill=MUTED)


def small_card(draw: ImageDraw.ImageDraw, *, x: int, y: int, w: int, title: str, body: str, accent: str = TEAL) -> int:
    body_lines = wrap_text(draw, body, FONT_SMALL, w - 36)
    h = 64 + len(body_lines) * 24
    rounded_panel(draw, (x, y, x + w, y + h), fill=PANEL)
    draw.text((x + 18, y + 16), title, font=FONT_BODY_BOLD, fill=accent)
    draw_wrapped(draw, body, x=x + 18, y=y + 46, font=FONT_SMALL, fill=MUTED, max_width=w - 36, line_gap=6)
    return h


def section_title(draw: ImageDraw.ImageDraw, *, x: int, y: int, title: str, eyebrow: str | None = None) -> int:
    cursor = y
    if eyebrow:
        draw.text((x, cursor), eyebrow, font=FONT_TINY, fill=TEAL)
        cursor += 24
    draw.text((x, cursor), title, font=FONT_H2, fill=TEXT)
    return cursor + 44


def bullet_block(draw: ImageDraw.ImageDraw, *, x: int, y: int, w: int, title: str, body: str, bg: str = PAPER) -> int:
    body_lines = wrap_text(draw, body, FONT_SMALL, w - 44)
    h = 58 + len(body_lines) * 24
    rounded_panel(draw, (x, y, x + w, y + h), fill=bg)
    draw.ellipse((x + 16, y + 18, x + 32, y + 34), fill=TEAL)
    draw.text((x + 42, y + 13), title, font=FONT_BODY_BOLD, fill=TEXT)
    draw_wrapped(draw, body, x=x + 42, y=y + 40, font=FONT_SMALL, fill=MUTED, max_width=w - 60, line_gap=6)
    return h


def step_block(draw: ImageDraw.ImageDraw, *, x: int, y: int, w: int, index: int, title: str, body: str) -> int:
    body_lines = wrap_text(draw, body, FONT_SMALL, w - 84)
    h = 62 + len(body_lines) * 22
    rounded_panel(draw, (x, y, x + w, y + h), fill=PANEL)
    draw.ellipse((x + 18, y + 18, x + 54, y + 54), fill=TEAL_SOFT, outline=LINE, width=1)
    idx = str(index)
    idx_w = text_width(draw, idx, FONT_BODY_BOLD)
    draw.text((x + 36 - idx_w / 2, y + 22), idx, font=FONT_BODY_BOLD, fill=TEAL)
    draw.text((x + 72, y + 14), title, font=FONT_BODY_BOLD, fill=TEXT)
    draw_wrapped(draw, body, x=x + 72, y=y + 40, font=FONT_SMALL, fill=MUTED, max_width=w - 90, line_gap=5)
    return h


def draw_table(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    widths: Sequence[int],
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    row_font: ImageFont.FreeTypeFont = FONT_SMALL,
) -> int:
    total_w = sum(widths)
    header_h = 42
    draw.rounded_rectangle((x, y, x + total_w, y + header_h), radius=16, fill=NAVY_SOFT, outline=LINE, width=1)
    cursor_x = x
    for index, header in enumerate(headers):
        draw.text((cursor_x + 10, y + 10), header, font=FONT_TINY, fill=NAVY)
        cursor_x += widths[index]
        if index < len(headers) - 1:
            draw.line((cursor_x, y + 4, cursor_x, y + header_h - 4), fill=LINE, width=1)
    cursor_y = y + header_h
    for row in rows:
        cell_lines = [wrap_text(draw, cell, row_font, widths[i] - 18) for i, cell in enumerate(row)]
        max_lines = max(len(lines) for lines in cell_lines)
        row_h = max(44, 14 + max_lines * 24)
        draw.rounded_rectangle((x, cursor_y, x + total_w, cursor_y + row_h), radius=0, fill=PANEL, outline=LINE, width=1)
        cx = x
        for idx, lines in enumerate(cell_lines):
            ty = cursor_y + 10
            for line in lines:
                draw.text((cx + 9, ty), line, font=row_font, fill=TEXT if idx == 0 else MUTED)
                ty += 22
            cx += widths[idx]
            if idx < len(cell_lines) - 1:
                draw.line((cx, cursor_y + 2, cx, cursor_y + row_h - 2), fill=LINE, width=1)
        cursor_y += row_h
    return cursor_y


@dataclass(frozen=True)
class PageBundle:
    image: Image.Image


def build_cover() -> PageBundle:
    image, draw = create_page()
    left_x = MARGIN
    top_y = MARGIN
    hero_w = 760
    right_x = PAGE_W - MARGIN - 320

    rounded_panel(draw, (left_x, top_y, left_x + hero_w, top_y + 370), fill=PANEL)
    draw.text((left_x + 26, top_y + 26), "EMBODIED AGENT ARCHITECTURE", font=FONT_TINY, fill=TEAL)
    draw.text((left_x + 26, top_y + 68), "Tracking Agent", font=FONT_H1, fill=TEXT)
    draw.text((left_x + 26, top_y + 132), "技术架构报告", font=FONT_H2, fill=TEXT)
    subtitle = "一个运行在 robot / Pi 侧的 chat-first embodied agent kernel。项目当前最核心的价值，在于把持续感知、事件驱动 turn、状态单源与 skill 插拔化收敛成清晰、可解释、可演进的系统骨架。"
    draw_wrapped(draw, subtitle, x=left_x + 26, y=top_y + 192, font=FONT_BODY, fill=MUTED, max_width=hero_w - 52, line_gap=9)
    pill_x = left_x + 26
    pill_y = top_y + 314
    for label in ["Chat-first", "Perception 常驻", "Single Runner", "Session Truth", "Skill-Pluggable"]:
        pill_w = pill(draw, x=pill_x, y=pill_y, text=label)
        pill_x += pill_w + 10

    metric_card(draw, x=right_x, y=top_y, w=150, number="3+1", label="推荐运行形态")
    metric_card(draw, x=right_x + 170, y=top_y, w=150, number="1", label="Session Truth")
    metric_card(draw, x=right_x, y=top_y + 144, w=150, number="Pi + Direct", label="决策路径")
    metric_card(draw, x=right_x + 170, y=top_y + 144, w=150, number="3", label="已验证 Skills")
    small_card(
        draw,
        x=right_x,
        y=top_y + 288,
        w=320,
        title="Inspection Scope",
        body="本报告基于仓库实态检查整理，聚焦系统设计、组件职责、状态与数据流、部署方式和扩展路径，不下钻到函数级实现。",
        accent=ORANGE,
    )

    left_panel_y = top_y + 404
    rounded_panel(draw, (left_x, left_panel_y, left_x + 530, left_panel_y + 1070), fill=PANEL)
    cy = section_title(draw, x=left_x + 22, y=left_panel_y + 20, title="项目目标与问题 framing", eyebrow="Project Goal")
    bullets = [
        ("目标不是单点 tracking demo", "仓库正在从 tracking-specific runtime 收敛为通用 embodied agent kernel，tracking 和 speech 是当前最明确的能力样板。"),
        ("要解决的是系统问题", "持续感知、会话状态、多轮对话、技能编排和展示层需要稳定协作，但不能演化成过度工程化的 runtime 框架。"),
        ("关键约束", "perception 负责提供世界状态，runner 负责单轮处理，viewer 负责状态投影，skills 负责具体 capability。"),
    ]
    for title, body in bullets:
        h = bullet_block(draw, x=left_x + 22, y=cy, w=486, title=title, body=body)
        cy += h + 14

    cy += 10
    draw.text((left_x + 22, cy), "Architecture Thesis", font=FONT_TINY, fill=ORANGE)
    cy += 24
    thesis = "系统最值得汇报的不是某个 tracking 算法细节，而是已经形成了“持续感知只做感知、单轮 runner 只做编排、状态只有一个真相源、skills 通过统一 surface 接入、viewer 只是展示层”的整体技术形态。"
    draw_wrapped(draw, thesis, x=left_x + 22, y=cy, font=FONT_BODY, fill=TEXT, max_width=486, line_gap=9)

    right_panel_x = left_x + 548
    rounded_panel(draw, (right_panel_x, left_panel_y, PAGE_W - MARGIN, left_panel_y + 1070), fill=PANEL)
    cy = section_title(draw, x=right_panel_x + 22, y=left_panel_y + 20, title="架构原则", eyebrow="Design Principles")
    principles = [
        ("Chat-first, not perception-first", "turn 由聊天、脚本或 loop 事件触发；perception 只提供 grounded context。", TEAL_SOFT),
        ("Perception is the only always-on subsystem", "只有 perception 常驻运行并持续写 observation 与 snapshot。", PAPER),
        ("Single runner path", "所有 turn 最终归并到 PiAgentRunner 的同一条主处理路径。", PAPER),
        ("Single persisted state truth", "session.json 是 agent-owned state 的主真相源。", TEAL_SOFT),
        ("Skills are ordinary modules", "tracking、speech、web_search 都通过统一 skill surface 接入。", PAPER),
        ("Viewer is a read-only projection", "viewer 聚合并展示状态，但不反向驱动业务逻辑。", TEAL_SOFT),
    ]
    for title, body, fill in principles:
        h = bullet_block(draw, x=right_panel_x + 22, y=cy, w=576, title=title, body=body, bg=fill)
        cy += h + 12

    footer(draw, 1, 7)
    return PageBundle(image)


def build_overview() -> PageBundle:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, title="系统全景与架构分层", eyebrow="System Overview")

    left_w = 520
    right_x = MARGIN + left_w + 20
    rounded_panel(draw, (MARGIN, cy, MARGIN + left_w, cy + 530), fill=PANEL)
    inner_y = cy + 20
    draw.text((MARGIN + 20, inner_y), "三条运行平面", font=FONT_H3, fill=TEXT)
    inner_y += 42
    planes = [
        ("Continuous Perception Plane", "scripts/run_tracking_perception.py 持续读取 camera / video，经过 LocalPerceptionService 写入 perception snapshot 与 keyframes。"),
        ("Turn Orchestration Plane", "backend/cli.py 与 PiAgentRunner 负责一次 turn 的上下文构造、skill 路由、Pi 调用或 deterministic direct path。"),
        ("Presentation Plane", "agent_viewer_stream 聚合 session + observation + viewer modules，经 websocket 提供给 tracking-viewer。"),
    ]
    for idx, (title, body) in enumerate(planes, start=1):
        h = step_block(draw, x=MARGIN + 20, y=inner_y, w=left_w - 40, index=idx, title=title, body=body)
        inner_y += h + 12

    rounded_panel(draw, (right_x, cy, PAGE_W - MARGIN, cy + 530), fill=PANEL)
    draw.text((right_x + 20, cy + 20), "高层结构关系", font=FONT_H3, fill=TEXT)
    layer_x1 = right_x + 26
    layer_x2 = PAGE_W - MARGIN - 26
    top = cy + 76
    layer_h = 72
    layers = [
        ("Trigger Layer", "User / Script / Tracking Loop"),
        ("Turn Orchestration", "backend/cli.py -> PiAgentRunner -> Pi or direct skill"),
        ("State Layer", "active_session.json + session.json + perception snapshot.json"),
        ("Capability Layer", "skills/tracking + skills/speech + skills/web_search"),
        ("Presentation Layer", "viewer stream websocket -> React app"),
        ("Continuous Perception", "camera / video -> perception service -> snapshot"),
    ]
    for idx, (title, body) in enumerate(layers):
        y = top + idx * (layer_h + 12)
        fill = TEAL_SOFT if idx % 2 == 0 else PAPER
        rounded_panel(draw, (layer_x1, y, layer_x2, y + layer_h), fill=fill, radius=20)
        draw.text((layer_x1 + 16, y + 12), title, font=FONT_BODY_BOLD, fill=TEXT)
        draw.text((layer_x1 + 16, y + 40), body, font=FONT_SMALL, fill=MUTED)

    table_y = cy + 560
    draw.text((MARGIN, table_y), "总体架构分层", font=FONT_H3, fill=TEXT)
    rows = [
        ("Trigger", "chat / loop / scripts", "产生 turn", "把事件触发从内核逻辑中剥离"),
        ("Orchestration", "runner + pi_protocol", "统一处理一次事件", "避免多条并行决策主链"),
        ("State", "session + snapshot", "落盘与共享状态", "确保单一真相源和可调试性"),
        ("Capability", "skills/<name>/", "实现具体能力", "新增能力不污染 backend 主干"),
        ("Presentation", "viewer stream + app", "聚合并展示状态", "保持 UI 为只读投影层"),
    ]
    draw_table(
        draw,
        x=MARGIN,
        y=table_y + 18,
        widths=[160, 260, 250, 384],
        headers=["Layer", "代表对象", "职责", "架构意义"],
        rows=rows,
    )

    footer(draw, 2, 7)
    return PageBundle(image)


def build_components() -> PageBundle:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, title="主要组件与职责", eyebrow="Major Components")
    rows = [
        ("Perception Service", "backend/perception/", "维护 observation window、keyframe、snapshot、CLI 读取接口", "持续感知层，但不做高层 orchestration"),
        ("Agent Runner", "backend/agent/runner.py", "接收 turn、生成上下文、调用 Pi 或 direct path、应用 payload", "系统唯一主处理链"),
        ("Pi Protocol", "backend/agent/pi_protocol.py", "定义 reasoning plane 的输入输出边界", "让 LLM 决策与本地状态管理解耦"),
        ("Session Persistence", "backend/persistence/", "维护 session.json 与 active_session.json", "保证单一状态真相源"),
        ("Skill Surface", "backend/skills.py", "统一 discovery、route summary、turn context、viewer module 聚合", "让 backend 保持通用"),
        ("Tracking Skill", "skills/tracking/", "target init、continue tracking、memory rewrite、viewer module", "当前最成熟的 embodied capability"),
        ("Speech / Web Search", "skills/speech/ + skills/web_search/", "TTS 与外部信息样例能力", "证明 plugability 不依赖 tracking 特例"),
        ("Viewer Stream", "backend/agent_viewer_stream.py", "聚合 agent / observation / modules 并经 websocket 输出", "将执行态转成展示态"),
        ("Frontend App", "apps/tracking-viewer/", "展示目标框、memory、conversation history、状态标签", "read-only projection layer"),
        ("Runtime Scripts", "scripts/", "启动 perception、loop、viewer、frontend、stack", "部署与进程编排层"),
    ]
    draw_table(
        draw,
        x=MARGIN,
        y=cy,
        widths=[170, 255, 365, 306],
        headers=["组件", "代表路径", "主要职责", "架构意义"],
        rows=rows,
    )

    lower_y = 1320
    rounded_panel(draw, (MARGIN, lower_y, MARGIN + 520, lower_y + 320), fill=PANEL)
    draw.text((MARGIN + 20, lower_y + 18), "Skill 接口为什么关键", font=FONT_H3, fill=TEXT)
    cards = [
        ("build_route_summary", "每个 skill 用自己的摘要参与 turn routing，而不是强迫 Pi 去阅读整份 session。"),
        ("build_turn_context", "为 skill 暴露专属上下文，缩小推理输入面。"),
        ("process_direct_init / turn", "为 fragile、确定性强的路径保留稳态入口。"),
        ("schedule_rewrite / build_viewer_module", "把慢操作和展示扩展下沉给 skill 自己。"),
    ]
    y = lower_y + 62
    for title, body in cards:
        h = bullet_block(draw, x=MARGIN + 18, y=y, w=484, title=title, body=body, bg=TEAL_SOFT)
        y += h + 10

    rounded_panel(draw, (MARGIN + 540, lower_y, PAGE_W - MARGIN, lower_y + 320), fill=PANEL)
    draw.text((MARGIN + 560, lower_y + 18), "Tracking Skill 的系统位置", font=FONT_H3, fill=TEXT)
    y = lower_y + 62
    tracking_notes = [
        ("它是 single-turn skill，不拥有 perception loop", "skills/tracking/SKILL.md 明确要求 tracking skill 只处理当前 turn。"),
        ("deterministic 入口比自由推理更重要", "init / track 走固定入口脚本，降低 fragile workflow 被 LLM 发散的概率。"),
        ("memory rewrite 脱离关键路径", "先确认目标与结果，再异步更新 tracking memory，优先保证主交互响应。"),
    ]
    for title, body in tracking_notes:
        h = bullet_block(draw, x=MARGIN + 558, y=y, w=504, title=title, body=body, bg=ORANGE_SOFT)
        y += h + 10

    footer(draw, 3, 7)
    return PageBundle(image)


def build_loop() -> PageBundle:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, title="Embodied Agent Loop", eyebrow="Perception -> Planning -> Action")

    left_w = 680
    rounded_panel(draw, (MARGIN, cy, MARGIN + left_w, cy + 1160), fill=PANEL)
    draw.text((MARGIN + 20, cy + 18), "标准 turn 处理路径", font=FONT_H3, fill=TEXT)
    steps = [
        ("Perception 持续写世界状态", "camera / video 输入被采样并形成 observation、detections、keyframes 和 persisted snapshot。"),
        ("外部事件触发一次 turn", "来源可以是用户 chat、tracking continuation loop 或脚本入口。"),
        ("Runner 聚合上下文", "读取 session.json 与 perception snapshot，生成 route context、skill context 和 turn context。"),
        ("Planning / Routing", "如果满足 deterministic 条件则走 direct path；否则由 Pi 在 enabled skills 中完成单轮路由。"),
        ("Action / Result", "skill 返回统一 JSON payload，包含 session_result、skill_state_patch、robot_response 等结构化结果。"),
        ("Persistence + Projection", "runner 应用状态更新；viewer stream 从持久化状态生成可视化投影；必要时异步执行 rewrite worker。"),
    ]
    y = cy + 66
    for index, (title, body) in enumerate(steps, start=1):
        h = step_block(draw, x=MARGIN + 20, y=y, w=left_w - 40, index=index, title=title, body=body)
        y += h + 12

    right_x = MARGIN + left_w + 20
    rounded_panel(draw, (right_x, cy, PAGE_W - MARGIN, cy + 540), fill=PANEL)
    draw.text((right_x + 20, cy + 18), "Perception / Planning / Action 的实际含义", font=FONT_H3, fill=TEXT)
    y = cy + 66
    semantic_cards = [
        ("Perception", "以 LocalPerceptionService 为中心，关注 frame、detections、window、snapshot 和 keyframe 保存。", TEAL_SOFT),
        ("Planning", "以 PiAgentRunner + Pi routing 为中心，决定该轮应该走哪个 skill、采用 Pi path 还是 direct path。", PAPER),
        ("Action", "当前更偏 capability result，例如 tracking 的 track / wait / ask，speech 的 TTS 输出，而不是完整机器人运动控制栈。", TEAL_SOFT),
    ]
    for title, body, fill in semantic_cards:
        h = bullet_block(draw, x=right_x + 18, y=y, w=378, title=title, body=body, bg=fill)
        y += h + 12

    rounded_panel(draw, (right_x, cy + 560, PAGE_W - MARGIN, cy + 1160), fill=PANEL)
    draw.text((right_x + 20, cy + 578), "为什么这不是一个“大 while 循环”", font=FONT_H3, fill=TEXT)
    narrative = [
        "仓库把持续感知和事件驱动 turn 明确拆开。",
        "这样做的结果是，系统既保留 embodied 状态感知能力，又避免把所有职责糅成一个难以替换、难以验证的大 runtime。",
        "tracking loop 只是 capability-oriented trigger，不是系统总控中心；viewer 只是投影层，不承担执行逻辑。",
    ]
    y = cy + 628
    for idx, text in enumerate(narrative, start=1):
        h = bullet_block(draw, x=right_x + 18, y=y, w=378, title=f"Key Point {idx}", body=text, bg=ORANGE_SOFT if idx == 2 else PAPER)
        y += h + 12
    px = right_x + 18
    py = cy + 1038
    for label in ["Perception 常驻", "Turn 单次处理", "Viewer 只读", "Rewrite 异步", "Loop 只是触发器"]:
        pw = pill(draw, x=px, y=py, text=label, fill=NAVY_SOFT, ink=NAVY)
        px += pw + 8
        if px > PAGE_W - MARGIN - 160:
            px = right_x + 18
            py += 44

    footer(draw, 4, 7)
    return PageBundle(image)


def build_dataflow() -> PageBundle:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, title="Runtime / Backend / App / Data Flow", eyebrow="Relationships")

    rounded_panel(draw, (MARGIN, cy, PAGE_W - MARGIN, cy + 280), fill=PANEL)
    draw.text((MARGIN + 20, cy + 18), "当前推荐运行形态：3 个长期进程 + 1 个可选前端", font=FONT_H3, fill=TEXT)
    card_y = cy + 78
    card_w = 256
    gap = 16
    process_cards = [
        ("Perception", "持续读取 camera / video，运行 detection / tracking，向共享状态写 observation。"),
        ("Tracking Loop", "轮询 session 与 perception，在目标已绑定时触发 continuation turn。"),
        ("Viewer Stream", "把聚合后的 agent / perception / module 状态通过 websocket 推给前端。"),
        ("Frontend", "React + Vite 演示界面，负责目标框、状态、记忆和对话记录的可视化。"),
    ]
    for idx, (title, body) in enumerate(process_cards):
        x = MARGIN + 20 + idx * (card_w + gap)
        rounded_panel(draw, (x, card_y, x + card_w, card_y + 160), fill=TEAL_SOFT if idx % 2 == 0 else PAPER, radius=22)
        draw.text((x + 16, card_y + 16), title, font=FONT_BODY_BOLD, fill=TEXT)
        draw_wrapped(draw, body, x=x + 16, y=card_y + 46, font=FONT_SMALL, fill=MUTED, max_width=card_w - 32, line_gap=6)

    table_y = cy + 310
    draw.text((MARGIN, table_y), "五种关系视角", font=FONT_H3, fill=TEXT)
    rows = [
        ("Runtime", "perception、loop、viewer、frontend", "共享同一 state-root / session_id 的进程集合", "职责清晰，可独立重启与组合"),
        ("Backend", "backend/", "perception、runner、persistence、viewer aggregation 所在内核层", "把主线保持在最小闭环里"),
        ("Skills", "skills/<name>/", "实现具体 capability 与 helper，不改变 backend 核心形状", "继续长能力而不是长框架"),
        ("App", "apps/tracking-viewer", "通过 websocket 消费聚合状态", "UI 与内核解耦"),
        ("Data Flow", "session + snapshot + artifacts", "共享文件状态连接多个进程与视图", "减少依赖，增强可调试性"),
    ]
    end_y = draw_table(
        draw,
        x=MARGIN,
        y=table_y + 18,
        widths=[130, 275, 395, 296],
        headers=["视角", "代表对象", "关系描述", "架构含义"],
        rows=rows,
    )

    artifacts_y = end_y + 30
    draw.text((MARGIN, artifacts_y), "关键状态对象", font=FONT_H3, fill=TEXT)
    artifact_cards = [
        ("Active Session", "active_session.json 指向当前活跃会话，是 perception、viewer、CLI 的共同索引。"),
        ("Session Truth", "sessions/<id>/session.json 保存 latest_result、history、recent_frames、skill_cache 等 agent-owned state。"),
        ("Perception Snapshot", "perception/sessions/<id>/snapshot.json 保存最新 observation、recent window、stream status 与 saved keyframes。"),
        ("Turn Artifacts", ".runtime/pi-agent/requests/... 保存 route context、skill context、prompt 等 turn 证据。"),
    ]
    x_positions = [MARGIN, MARGIN + 560]
    y_positions = [artifacts_y + 18, artifacts_y + 142]
    idx = 0
    for y in y_positions:
        for x in x_positions:
            title, body = artifact_cards[idx]
            small_card(draw, x=x, y=y, w=536, title=title, body=body, accent=NAVY)
            idx += 1

    footer(draw, 5, 7)
    return PageBundle(image)


def build_tradeoffs() -> PageBundle:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, title="设计理由、Tradeoffs 与可扩展性", eyebrow="Rationale")

    rounded_panel(draw, (MARGIN, cy, PAGE_W - MARGIN, cy + 780), fill=PANEL)
    draw.text((MARGIN + 20, cy + 18), "关键设计取舍", font=FONT_H3, fill=TEXT)
    tradeoffs = [
        ("Chat-first vs perception-first", "turn 由聊天或事件触发，perception 只提供 grounded context；适合 agent interaction，但未来高频闭环控制仍需更硬实时的 control plane。"),
        ("Single session truth vs 多份 memory", "session.json 让调试和 viewer 聚合都有统一落点，但当前更偏单机和单活跃 session 形态。"),
        ("File-backed shared state vs event bus", "本地共享文件简单、直观、易部署，但不以分布式吞吐和强一致消息语义为目标。"),
        ("Direct path vs full LLM mediation", "tracking 的 init / track 支持 deterministic 入口，让 fragile workflow 更稳，但 skill 需要承担更明确的契约维护。"),
        ("Async rewrite vs inline completion", "主 turn 响应更快，但 memory 更新变成 eventual consistency。"),
        ("Generic viewer shell vs tracking-only UI", "viewer 可继续承载更多 skill 模块，但公共 schema 必须保持克制，避免重新长成大框架。"),
    ]
    box_w = 520
    x_values = [MARGIN + 20, MARGIN + 20 + box_w + 16]
    y = cy + 70
    row_h = 220
    idx = 0
    for row in range(3):
        for col in range(2):
            x = x_values[col]
            fill = ORANGE_SOFT if (idx % 2 == 0) else TEAL_SOFT
            h = bullet_block(draw, x=x, y=y, w=box_w, title=tradeoffs[idx][0], body=tradeoffs[idx][1], bg=fill)
            _ = h
            idx += 1
        y += row_h

    lower_y = cy + 820
    rounded_panel(draw, (MARGIN, lower_y, MARGIN + 548, lower_y + 690), fill=PANEL)
    draw.text((MARGIN + 20, lower_y + 18), "扩展性判断", font=FONT_H3, fill=TEXT)
    y = lower_y + 68
    extensibility = [
        ("已经具备的扩展点", "新增 skill 可以放在 skills/<name>/，backend 自动发现，并在 route summary、turn context、viewer module、direct path 等协作点接入。"),
        ("当前刻意不做的事", "不引入复杂 plugin lifecycle、不引入消息总线、不把 tracking loop 升级为总控中心，以避免再次回到过度工程化路径。"),
        ("最重要的判断", "仓库已经具备“继续长能力而不是继续长框架”的结构条件。"),
    ]
    for title, body in extensibility:
        h = bullet_block(draw, x=MARGIN + 20, y=y, w=508, title=title, body=body, bg=PAPER if "不做" in title else TEAL_SOFT)
        y += h + 12

    rounded_panel(draw, (MARGIN + 568, lower_y, PAGE_W - MARGIN, lower_y + 690), fill=PANEL)
    draw.text((MARGIN + 588, lower_y + 18), "部署判断", font=FONT_H3, fill=TEXT)
    y = lower_y + 68
    deploy_items = [
        ("进程职责清晰", "perception、loop、viewer 可分别重启和定位问题，不会形成单点超级进程。"),
        ("Viewer 可选", "前端不再是主流程依赖，既适合 headless，也适合演示。"),
        ("状态共享简单", "共享同一 state-root 和 session 路径即可运行，贴合 robot / Pi 侧轻量部署。"),
        ("能力替换容易", "perception 源、skills 和展示层都可以演进，而不需要先改内核。"),
    ]
    for title, body in deploy_items:
        h = bullet_block(draw, x=MARGIN + 588, y=y, w=500, title=title, body=body, bg=NAVY_SOFT if "Viewer" in title else PAPER)
        y += h + 12

    footer(draw, 6, 7)
    return PageBundle(image)


def build_future() -> PageBundle:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, title="边界、Future Work 与总结", eyebrow="Outlook")

    rounded_panel(draw, (MARGIN, cy, MARGIN + 520, cy + 590), fill=PANEL)
    draw.text((MARGIN + 20, cy + 18), "当前边界与成熟度", font=FONT_H3, fill=TEXT)
    y = cy + 72
    boundaries = [
        ("最成熟的 embodied capability 仍然是 tracking", "speech 与 web_search 已经证明 plugability，但 embodied 主场景仍围绕 tracking。"),
        ("状态共享主要是本地文件级协作", "这非常适合单机部署和调试，但不等于已经具备跨机分布式架构。"),
        ("Action plane 仍偏结果型输出", "当前重点是 grounded 决策与能力执行，而不是完整机器人控制栈。"),
        ("Perception 仍聚焦 tracking 场景", "它已经是独立感知层，但还不是通用多传感器融合平台。"),
    ]
    for title, body in boundaries:
        h = bullet_block(draw, x=MARGIN + 20, y=y, w=480, title=title, body=body, bg=PAPER if "Action" in title else ORANGE_SOFT)
        y += h + 12

    rounded_panel(draw, (MARGIN + 540, cy, PAGE_W - MARGIN, cy + 590), fill=PANEL)
    draw.text((MARGIN + 560, cy + 18), "Future Work", font=FONT_H3, fill=TEXT)
    y = cy + 72
    futures = [
        ("更强的部署韧性", "为 perception、loop、viewer 增加更明确的健康检查、超时与恢复策略。"),
        ("更通用的 capability surface", "在保持 skill surface 克制的前提下，接入更多 embodied 能力。"),
        ("更强的 observability", "补齐 turn latency、skill routing、rewrite worker、session lifecycle 等指标。"),
        ("多设备 / 远程部署能力", "如果跨机部署成为刚需，再从本地文件共享迁移到更明确的 service / bus 架构。"),
    ]
    for idx, (title, body) in enumerate(futures, start=1):
        box_fill = TEAL_SOFT if idx % 2 == 1 else PAPER
        h = bullet_block(draw, x=MARGIN + 560, y=y, w=460, title=f"{idx}. {title}", body=body, bg=box_fill)
        y += h + 12

    rounded_panel(draw, (MARGIN, cy + 620, PAGE_W - MARGIN, PAGE_H - 110), fill=PANEL)
    draw.text((MARGIN + 24, cy + 642), "汇报结论", font=FONT_H3, fill=TEXT)
    conclusion = (
        "tracking_agent 当前最值得强调的成果，不是某一个 tracking 算法细节，而是已经把 embodied agent 方案压缩成一个可解释、可部署、可扩展的技术骨架。"
    )
    draw_wrapped(draw, conclusion, x=MARGIN + 24, y=cy + 690, font=FONT_BODY, fill=TEXT, max_width=PAGE_W - MARGIN * 2 - 48, line_gap=9)
    px = MARGIN + 24
    py = cy + 772
    for label in ["持续感知只做感知", "单轮 runner 只做编排", "状态只有一个真相源", "skills 通过统一 surface 接入", "viewer 只是展示层"]:
        pw = pill(draw, x=px, y=py, text=label, fill=TEAL_SOFT, ink=TEAL)
        px += pw + 10
        if px > PAGE_W - MARGIN - 160:
            px = MARGIN + 24
            py += 46
    closing = (
        "这让项目从“为 tracking 服务的一组脚本”演进为“以 tracking 为样板能力的 embodied agent kernel”。对外汇报时，应把这种系统级收敛能力作为主叙事。"
    )
    draw_wrapped(draw, closing, x=MARGIN + 24, y=py + 70, font=FONT_BODY, fill=MUTED, max_width=PAGE_W - MARGIN * 2 - 48, line_gap=9)

    footer(draw, 7, 7)
    return PageBundle(image)


def main() -> None:
    bundles = [
        build_cover(),
        build_overview(),
        build_components(),
        build_loop(),
        build_dataflow(),
        build_tradeoffs(),
        build_future(),
    ]
    images = [bundle.image.convert("RGB") for bundle in bundles]
    images[0].save(
        OUTPUT_PDF,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=images[1:],
    )
    print(f"wrote {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
