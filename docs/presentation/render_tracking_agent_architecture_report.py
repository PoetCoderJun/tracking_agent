from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUTPUT_PDF = ROOT / "tracking-agent-embodied-architecture-report.pdf"
PAGE_W = 1240
PAGE_H = 1754
MARGIN = 72

BG = "#f6efe6"
PAPER = "#fffaf4"
PANEL = "#fffdf9"
TEXT = "#1f1b17"
MUTED = "#655b52"
LINE = "#ddd2c5"
TEAL = "#0d6b63"
TEAL_SOFT = "#e8f4f1"
ORANGE = "#b85b2f"
ORANGE_SOFT = "#f8ece4"
NAVY = "#223650"
NAVY_SOFT = "#ebf0f6"
SHADOW = "#efe6da"

FONT_REGULAR = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_MONO = "/System/Library/Fonts/Helvetica.ttc"


def font(size: int, *, bold: bool = False, mono: bool = False):
    path = FONT_MONO if mono else (FONT_BOLD if bold else FONT_REGULAR)
    return ImageFont.truetype(path, size=size)


FONT_TINY = font(12, bold=True)
FONT_SMALL = font(16)
FONT_BODY = font(19)
FONT_BODY_BOLD = font(19, bold=True)
FONT_H3 = font(24, bold=True)
FONT_H2 = font(32, bold=True)
FONT_H1 = font(52, bold=True)
FONT_METRIC = font(28, bold=True)
FONT_MONO_SMALL = font(16, mono=True)


def text_w(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    for para in text.split("\n"):
        if para == "":
            lines.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if not cur or text_w(draw, trial, fnt) <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines or [""]


def draw_text(draw, text: str, *, x: int, y: int, fnt, fill: str, max_width: int, gap: int = 8) -> int:
    lines = wrap(draw, text, fnt, max_width)
    line_h = draw.textbbox((0, 0), "测试Ag", font=fnt)[3] + gap
    cy = y
    for line in lines:
        draw.text((x, cy), line, font=fnt, fill=fill)
        cy += line_h
    return cy


def panel(draw, box: tuple[int, int, int, int], *, fill: str = PANEL, radius: int = 28):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 6, y1 + 8, x2 + 6, y2 + 8), radius=radius, fill=SHADOW)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=LINE, width=2)


def section_title(draw, *, x: int, y: int, eyebrow: str, title: str) -> int:
    draw.text((x, y), eyebrow, font=FONT_TINY, fill=TEAL)
    draw.text((x, y + 24), title, font=FONT_H2, fill=TEXT)
    return y + 74


def pill(draw, *, x: int, y: int, text: str, fill: str = TEAL_SOFT, ink: str = TEAL) -> int:
    w = text_w(draw, text, FONT_SMALL) + 30
    draw.rounded_rectangle((x, y, x + w, y + 34), radius=17, fill=fill, outline=LINE, width=1)
    draw.text((x + 15, y + 7), text, font=FONT_SMALL, fill=ink)
    return w


def metric(draw, *, x: int, y: int, w: int, number: str, label: str):
    panel(draw, (x, y, x + w, y + 120))
    draw.text((x + 18, y + 18), number, font=FONT_METRIC, fill=TEXT)
    draw_text(draw, label, x=x + 18, y=y + 62, fnt=FONT_SMALL, fill=MUTED, max_width=w - 36, gap=4)


def card(draw, *, x: int, y: int, w: int, title: str, body: str, fill: str = PANEL) -> int:
    lines = wrap(draw, body, FONT_SMALL, w - 32)
    h = 56 + len(lines) * 23
    panel(draw, (x, y, x + w, y + h), fill=fill, radius=20)
    draw.text((x + 16, y + 14), title, font=FONT_BODY_BOLD, fill=TEXT)
    draw_text(draw, body, x=x + 16, y=y + 40, fnt=FONT_SMALL, fill=MUTED, max_width=w - 32, gap=5)
    return h


def story_step(draw, *, x: int, y: int, w: int, idx: int, title: str, body: str, fill: str) -> int:
    lines = wrap(draw, body, FONT_SMALL, w - 92)
    h = 58 + len(lines) * 22
    panel(draw, (x, y, x + w, y + h), fill=fill, radius=22)
    draw.ellipse((x + 16, y + 14, x + 54, y + 52), fill="white", outline=LINE, width=1)
    n = str(idx)
    draw.text((x + 35 - text_w(draw, n, FONT_BODY_BOLD) / 2, y + 18), n, font=FONT_BODY_BOLD, fill=TEAL)
    draw.text((x + 70, y + 12), title, font=FONT_BODY_BOLD, fill=TEXT)
    draw_text(draw, body, x=x + 70, y=y + 38, fnt=FONT_SMALL, fill=MUTED, max_width=w - 86, gap=4)
    return h


def footer(draw, page_no: int, total: int):
    draw.text((MARGIN, PAGE_H - 40), "Tracking Agent Storytelling Architecture Report", font=FONT_SMALL, fill=MUTED)
    label = f"{page_no} / {total}"
    draw.text((PAGE_W - MARGIN - text_w(draw, label, FONT_SMALL), PAGE_H - 40), label, font=FONT_SMALL, fill=MUTED)


def create_page():
    image = Image.new("RGB", (PAGE_W, PAGE_H), BG)
    draw = ImageDraw.Draw(image)
    draw.ellipse((-120, -80, 240, 260), fill=TEAL_SOFT)
    draw.ellipse((PAGE_W - 270, -90, PAGE_W + 80, 230), fill=ORANGE_SOFT)
    return image, draw


@dataclass(frozen=True)
class Page:
    image: Image.Image


def page1() -> Page:
    image, draw = create_page()
    hero_h = 400
    panel(draw, (MARGIN, MARGIN, PAGE_W - MARGIN, MARGIN + hero_h), fill=PANEL)
    draw.text((MARGIN + 28, MARGIN + 26), "EMBODIED AGENT STORYTELLING REPORT", font=FONT_TINY, fill=TEAL)
    draw.text((MARGIN + 28, MARGIN + 72), "Tracking Agent", font=FONT_H1, fill=TEXT)
    draw.text((MARGIN + 28, MARGIN + 136), "不是“会框人”，而是“会持续理解任务”的机器人运行骨架", font=FONT_H2, fill=TEXT)
    lead = "如果只看算法，这像一个 tracking 系统；如果站在系统设计角度看，它其实是在回答一个更大的问题：机器人怎样把“持续看世界”和“理解人类任务”接成一条真正可用的链。"
    draw_text(draw, lead, x=MARGIN + 28, y=MARGIN + 204, fnt=FONT_BODY, fill=MUTED, max_width=700, gap=8)
    px = MARGIN + 28
    for label in ["Chat-first", "Perception 常驻", "Single Runner", "Session Truth", "Skill-Pluggable"]:
        pw = pill(draw, x=px, y=MARGIN + 326, text=label)
        px += pw + 10

    metric_x = PAGE_W - MARGIN - 320
    metric(draw, x=metric_x, y=MARGIN + 26, w=150, number="3+1", label="推荐运行形态")
    metric(draw, x=metric_x + 170, y=MARGIN + 26, w=150, number="1", label="状态真相源")
    metric(draw, x=metric_x, y=MARGIN + 162, w=150, number="Pi + Direct", label="决策路径")
    metric(draw, x=metric_x + 170, y=MARGIN + 162, w=150, number="Tracking", label="成熟能力样板")

    y = MARGIN + hero_h + 18
    left_w = 530
    panel(draw, (MARGIN, y, MARGIN + left_w, y + 1080))
    cy = section_title(draw, x=MARGIN + 22, y=y + 20, eyebrow="WHY THE PROJECT EXISTS", title="为什么普通 tracking demo 不够？")
    for title, body, fill in [
        ("它能框人，但不一定能理解任务", "用户说的是“跟着最开始出现的穿黑衣服的人”，不是“跟踪 ID 7”。系统必须先理解语义，再执行。", ORANGE_SOFT),
        ("它能追一帧，但不一定能维持连续状态", "真正的机器人不是处理单帧图像，而是要跨多轮、跨时间地记住“我现在正在跟谁”。", PANEL),
        ("它能显示画框，但不一定能解释自己在做什么", "如果没有统一状态与展示层，用户看到的只是框，看不到系统为什么这样选、下一步准备做什么。", TEAL_SOFT),
    ]:
        h = card(draw, x=MARGIN + 22, y=cy, w=486, title=title, body=body, fill=fill)
        cy += h + 12

    cy += 10
    draw.text((MARGIN + 22, cy), "真正难的，不是某个模型强不强，而是整条链必须连起来。", font=FONT_BODY_BOLD, fill=TEXT)
    cy += 36
    for bullet in [
        "机器人能不能一直看着现实世界？",
        "用户能不能用自然语言告诉它“去跟着那个人”？",
        "系统能不能把“那个人是谁”记住，而不是每一轮都重新猜？",
        "当目标短暂丢失、重新出现、或用户要求切换时，系统能不能继续工作？",
    ]:
        draw.ellipse((MARGIN + 22, cy + 7, MARGIN + 34, cy + 19), fill=TEAL)
        draw_text(draw, bullet, x=MARGIN + 44, y=cy, fnt=FONT_BODY, fill=MUTED, max_width=460, gap=6)
        cy += 44

    right_x = MARGIN + left_w + 20
    panel(draw, (right_x, y, PAGE_W - MARGIN, y + 1080))
    cy = section_title(draw, x=right_x + 22, y=y + 20, eyebrow="THE REAL GOAL", title="这个项目真正想解决什么？")
    blocks = [
        ("持续感知", "机器人一直在看世界，不需要每次等用户开口才“醒过来”。", TEAL_SOFT),
        ("对话驱动的任务理解", "用户用自然语言发任务，系统把当前世界状态和历史状态一起拿来解释这句话。", NAVY_SOFT),
        ("单一状态真相源", "系统必须稳定记住“我正在跟谁、上一步发生了什么”，而不是让多个缓存互相猜。", ORANGE_SOFT),
        ("能力可扩展", "tracking 只是第一能力样板，speech、web_search 乃至更多 embodied skill 都要能自然接进来。", PANEL),
    ]
    for title, body, fill in blocks:
        h = card(draw, x=right_x + 22, y=cy, w=576, title=title, body=body, fill=fill)
        cy += h + 12
    quote_y = cy + 18
    panel(draw, (right_x + 22, quote_y, PAGE_W - MARGIN - 22, quote_y + 180), fill=ORANGE_SOFT, radius=24)
    quote = "它想解决的不是“目标检测准不准”这一个点，而是怎样把 perception、对话理解、状态持久化、技能调用和展示层，收敛成同一个 agent runtime。"
    draw_text(draw, quote, x=right_x + 42, y=quote_y + 34, fnt=FONT_BODY, fill=TEXT, max_width=536, gap=8)

    footer(draw, 1, 6)
    return Page(image)


def page2() -> Page:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, eyebrow="CORE THESIS", title="这套方案最聪明的地方：不让任何一个模块变成“整个系统”")
    top_y = cy
    left_w = 550
    panel(draw, (MARGIN, top_y, MARGIN + left_w, top_y + 600))
    y = top_y + 20
    for title, body, fill in [
        ("Perception 只负责“看见”", "它持续读 camera / video、产出 observation、保存 keyframe 和 snapshot，但不替系统做高层决策。", TEAL_SOFT),
        ("Runner 只负责“这一轮”", "每来一个 turn，就认真处理完这一轮：读状态、组上下文、选 skill 路径、落盘结果。", ORANGE_SOFT),
        ("Session state 只有一个主真相源", "session.json 把“我正在跟谁、上一轮结果是什么、skill 记住了什么”稳定收在一个地方。", NAVY_SOFT),
        ("Skill 是能力模块，不是系统分叉", "tracking、speech、web_search 都通过统一 surface 接入，backend 主干不因新能力而变形。", PANEL),
        ("Viewer 只负责让人看懂", "viewer 是 read-only projection layer，负责显示系统状态，而不是控制业务逻辑。", TEAL_SOFT),
    ]:
        h = card(draw, x=MARGIN + 20, y=y, w=510, title=title, body=body, fill=fill)
        y += h + 12

    right_x = MARGIN + left_w + 20
    panel(draw, (right_x, top_y, PAGE_W - MARGIN, top_y + 600))
    draw.text((right_x + 20, top_y + 20), "如果把整套系统压缩成一张图", font=FONT_H3, fill=TEXT)
    panel(draw, (right_x + 20, top_y + 70, PAGE_W - MARGIN - 20, top_y + 520), fill="#fffaf8", radius=22)
    diagram = "现实世界（camera / video）\n        ↓\n[ Perception Service ]\n持续写 detection / tracking / snapshot\n        ↓\n[ Persisted World State ]\n最近画面、关键帧、snapshot\n        ↓\n用户 / loop / script 触发一次 turn\n        ↓\n[ PiAgentRunner ]\n读取 session + perception，生成 route context\n        ↓\n[ Skill Execution ]\ntracking / speech / web_search\n        ↓\n[ Session Truth ]\nlatest_result / skill_cache / history\n        ↓\n[ Viewer Stream ]\n把系统状态投影给前端\n        ↓\n[ Frontend ]\n让人看懂系统现在“看到什么、记得什么、准备做什么”"
    draw_text(draw, diagram, x=right_x + 44, y=top_y + 102, fnt=FONT_MONO_SMALL, fill=TEXT, max_width=500, gap=8)

    lower_y = top_y + 620
    panel(draw, (MARGIN, lower_y, PAGE_W - MARGIN, lower_y + 900))
    draw.text((MARGIN + 22, lower_y + 20), "五个架构关键词", font=FONT_H3, fill=TEXT)
    px = MARGIN + 22
    py = lower_y + 70
    for label, fill, ink in [
        ("Chat-first", TEAL_SOFT, TEAL),
        ("Perception 常驻", TEAL_SOFT, TEAL),
        ("Single Runner", NAVY_SOFT, NAVY),
        ("Session Truth", ORANGE_SOFT, ORANGE),
        ("Skill-Pluggable", TEAL_SOFT, TEAL),
        ("Viewer 只读", NAVY_SOFT, NAVY),
    ]:
        pw = pill(draw, x=px, y=py, text=label, fill=fill, ink=ink)
        px += pw + 10
    rows = [
        ("Chat-first, not perception-first", "turn 由聊天、脚本或 loop 事件触发；perception 负责提供 grounded context。"),
        ("Perception is the only always-on subsystem", "只有 perception 常驻运行；其余组件围绕一次次 turn 工作。"),
        ("Single runner path", "所有 turn 最终都收敛到 PiAgentRunner 这一条主处理链。"),
        ("Single persisted state truth", "session.json 是 agent-owned state 的主真相源。"),
        ("Skills are ordinary modules", "tracking、speech、web_search 都通过统一 skill surface 接入。"),
    ]
    y = lower_y + 130
    for title, body in rows:
        h = card(draw, x=MARGIN + 22, y=y, w=1072, title=title, body=body, fill=PANEL)
        y += h + 12

    footer(draw, 2, 6)
    return Page(image)


def page3() -> Page:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, eyebrow="TELL IT LIKE A STORY", title="用一个真实场景，讲完整套 embodied agent 流程")
    panel(draw, (MARGIN, cy, PAGE_W - MARGIN, PAGE_H - 100))
    draw.text((MARGIN + 24, cy + 20), "场景：用户说“开始跟踪最开始出现的穿黑衣服的人。”", font=FONT_H3, fill=TEXT)
    y = cy + 70
    steps = [
        ("系统先看到世界", "Perception 服务一直在跑，不需要等用户下命令。它像机器人的眼睛，持续把“现在看到了什么”写成 snapshot。", TEAL_SOFT),
        ("用户给出的是语义任务，不是 track id", "“最开始出现的穿黑衣服的人”是一句带上下文、带歧义空间的话。系统不能直接执行，它要先理解。", ORANGE_SOFT),
        ("Runner 组装这次 turn 的完整上下文", "它把最近对话、当前世界和已有 session 状态拼起来。于是系统不是“听一句话”，而是“带着记忆去理解一句话”。", NAVY_SOFT),
        ("该自由发挥的地方让模型发挥，该收紧的地方就收紧", "tracking init / track 这种 fragile workflow，优先走 deterministic entry script，而不是完全依赖开放式 LLM 推理。", TEAL_SOFT),
        ("目标一旦确认，就正式写进 session", "系统不是“这轮猜到是谁了”，而是“从这一刻起，我正式知道自己正在跟谁”。", ORANGE_SOFT),
        ("Tracking loop 负责持续推进，但不是系统总控", "它只在 tracking 这个能力上推动 continuation / recovery，不把整个 runtime 拖进一个大 while loop。", NAVY_SOFT),
        ("Viewer 负责把系统脑子里的想法展示出来", "用户能看到目标框、记忆、对话和当前状态；系统因此变得可解释、可观察、可调试。", TEAL_SOFT),
    ]
    for idx, (title, body, fill) in enumerate(steps, start=1):
        h = story_step(draw, x=MARGIN + 24, y=y, w=1070, idx=idx, title=title, body=body, fill=fill)
        y += h + 12

    footer(draw, 3, 6)
    return Page(image)


def page4() -> Page:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, eyebrow="CAST LIST", title="主要组件，换成“角色表”来讲")
    panel(draw, (MARGIN, cy, PAGE_W - MARGIN, cy + 720))
    headers = ["角色", "代表路径", "它在故事里扮演什么角色"]
    widths = [150, 320, 594]
    x = MARGIN + 20
    y = cy + 24
    total_w = sum(widths)
    draw.rounded_rectangle((x, y, x + total_w, y + 42), radius=16, fill=NAVY_SOFT, outline=LINE, width=1)
    cx = x
    for i, h in enumerate(headers):
        draw.text((cx + 10, y + 10), h, font=FONT_TINY, fill=NAVY)
        cx += widths[i]
        if i < len(headers) - 1:
            draw.line((cx, y + 5, cx, y + 37), fill=LINE, width=1)
    rows = [
        ("眼睛", "backend/perception/", "持续看世界，把 observation、snapshot、keyframe 写下来"),
        ("单轮工作台", "backend/agent/runner.py", "处理一次 turn：读状态、组上下文、选路径、落结果"),
        ("决策边界", "backend/agent/pi_protocol.py", "规定 Pi 能读什么、该返回什么"),
        ("记忆本", "backend/persistence/ + session.json", "把“系统当前正在做什么”稳稳记住"),
        ("技能面板", "backend/skills.py", "让 tracking / speech / web_search 以统一方式接进来"),
        ("主力能力", "skills/tracking/", "做目标初始化、持续跟踪、记忆更新与 viewer 模块"),
        ("展示层", "agent_viewer_stream + tracking-viewer", "把系统状态翻译成人类可读的 UI"),
        ("舞台监督", "scripts/", "把 perception、loop、viewer、frontend 分别启动起来"),
    ]
    cy2 = y + 42
    for row in rows:
        cell_lines = [wrap(draw, row[i], FONT_SMALL, widths[i] - 20) for i in range(3)]
        max_lines = max(len(c) for c in cell_lines)
        rh = max(46, 16 + max_lines * 24)
        draw.rectangle((x, cy2, x + total_w, cy2 + rh), fill=PANEL, outline=LINE, width=1)
        cx = x
        for i, lines in enumerate(cell_lines):
            yy = cy2 + 10
            for line in lines:
                draw.text((cx + 10, yy), line, font=FONT_SMALL if i else FONT_BODY_BOLD, fill=TEXT if i == 0 else MUTED)
                yy += 22
            cx += widths[i]
            if i < 2:
                draw.line((cx, cy2 + 2, cx, cy2 + rh - 2), fill=LINE, width=1)
        cy2 += rh

    lower_y = cy + 750
    left_w = 540
    panel(draw, (MARGIN, lower_y, MARGIN + left_w, PAGE_H - 100))
    draw.text((MARGIN + 20, lower_y + 18), "为什么这种分工舒服？", font=FONT_H3, fill=TEXT)
    y = lower_y + 66
    for title, body, fill in [
        ("因为你能一眼看出谁负责什么", "一套系统只要角色分工清楚，它就更容易维护，也更容易解释给别人听。", TEAL_SOFT),
        ("因为新增能力不会逼 backend 变形", "新 skill 往 skills/<name>/ 里接，不需要把主干 runtime 再拆一遍。", ORANGE_SOFT),
        ("因为系统主线永远只有一条", "不是 perception 一套逻辑、loop 一套逻辑、前端一套逻辑各说各话，而是统一回到 runner 和 session truth。", NAVY_SOFT),
    ]:
        h = card(draw, x=MARGIN + 20, y=y, w=500, title=title, body=body, fill=fill)
        y += h + 12

    right_x = MARGIN + left_w + 20
    panel(draw, (right_x, lower_y, PAGE_W - MARGIN, PAGE_H - 100))
    draw.text((right_x + 20, lower_y + 18), "部署方式也很“人能理解”", font=FONT_H3, fill=TEXT)
    y = lower_y + 70
    for title, body, fill in [
        ("Perception", "一直看世界，负责把现实变成机器可读状态。", TEAL_SOFT),
        ("Tracking Loop", "在 tracking 语境里推动 continuation / recovery。", ORANGE_SOFT),
        ("Viewer Stream + Frontend", "把系统状态变成用户可见的界面。", NAVY_SOFT),
    ]:
        h = card(draw, x=right_x + 20, y=y, w=500, title=title, body=body, fill=fill)
        y += h + 12
    summary = "“3 个长期进程 + 1 个可选前端”的部署方式不花哨，但特别实用：职责分离、定位清楚、前端可选、单机易跑。"
    draw_text(draw, summary, x=right_x + 20, y=y + 10, fnt=FONT_BODY, fill=MUTED, max_width=500, gap=7)

    footer(draw, 4, 6)
    return Page(image)


def page5() -> Page:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, eyebrow="TRADEOFFS", title="这套方案的成熟，不在于没有边界，而在于边界讲得清楚")
    left_w = 550
    panel(draw, (MARGIN, cy, MARGIN + left_w, PAGE_H - 100))
    draw.text((MARGIN + 20, cy + 18), "要诚实地讲它的边界", font=FONT_H3, fill=TEXT)
    y = cy + 70
    for title, body, fill in [
        ("它更像 embodied decision kernel，不是完整 motion stack", "现在更强的是“看、记、理解、执行 capability”的闭环，而不是完整机器人运动控制闭环。", ORANGE_SOFT),
        ("它非常适合单机 / 单 session，但还不是分布式多机系统", "本地文件共享状态对当前阶段特别合理，但未来跨设备部署需要更明确的 service / bus 边界。", PANEL),
        ("tracking 是当前最成熟的 embodied capability", "这不是短板，反而证明项目在先把一个核心能力打磨到位，而不是空泛许愿。", TEAL_SOFT),
    ]:
        h = card(draw, x=MARGIN + 20, y=y, w=510, title=title, body=body, fill=fill)
        y += h + 14

    panel(draw, (MARGIN + left_w + 20, cy, PAGE_W - MARGIN, PAGE_H - 100))
    draw.text((MARGIN + left_w + 40, cy + 18), "最值得肯定的设计取舍", font=FONT_H3, fill=TEXT)
    y = cy + 70
    for title, body, fill in [
        ("不把 perception 变成大脑", "感知层长期跑，但不越权做高层决策。", TEAL_SOFT),
        ("不把 tracking loop 变成总控中心", "loop 只是 tracking 能力的推进器，不绑架整个 runtime 形状。", ORANGE_SOFT),
        ("不让 LLM 包办脆弱流程", "tracking init / track 走 deterministic entry script，这是一种成熟的工程选择。", NAVY_SOFT),
        ("不让 viewer 决定系统怎么运行", "viewer 只负责让人看懂，不反向塑造业务逻辑。", PANEL),
    ]:
        h = card(draw, x=MARGIN + left_w + 40, y=y, w=510, title=title, body=body, fill=fill)
        y += h + 12
    panel(draw, (MARGIN + left_w + 40, y + 14, PAGE_W - MARGIN - 20, y + 180), fill=ORANGE_SOFT, radius=22)
    quote = "这套架构真正成熟的地方，不在于它“什么都做”，而在于它知道哪些事情现在该做，哪些事情暂时不要装成已经做好了。"
    draw_text(draw, quote, x=MARGIN + left_w + 62, y=y + 54, fnt=FONT_BODY, fill=TEXT, max_width=466, gap=8)

    footer(draw, 5, 6)
    return Page(image)


def page6() -> Page:
    image, draw = create_page()
    cy = section_title(draw, x=MARGIN, y=MARGIN, eyebrow="OUTLOOK", title="Future Work，以及你上台时最应该怎么讲")
    left_w = 560
    panel(draw, (MARGIN, cy, MARGIN + left_w, cy + 730))
    draw.text((MARGIN + 20, cy + 18), "下一步最值得长什么？", font=FONT_H3, fill=TEXT)
    y = cy + 70
    for title, body, fill in [
        ("更强的部署韧性", "补齐 perception、loop、viewer 的健康检查、恢复与异常处理，让它更像持续运行系统。", TEAL_SOFT),
        ("更多 embodied capabilities", "沿着现有 skill surface 接入 spatial QA、action recommendation、multimodal memory 等新能力。", ORANGE_SOFT),
        ("更强的 observability", "系统化记录 turn latency、route decision、rewrite worker 成功率和 recovery 质量。", NAVY_SOFT),
        ("远程 / 多设备部署", "当跨机部署成为刚需时，再把当前清晰边界升级成真正的 service 边界。", PANEL),
    ]:
        h = card(draw, x=MARGIN + 20, y=y, w=520, title=title, body=body, fill=fill)
        y += h + 12

    panel(draw, (MARGIN + left_w + 20, cy, PAGE_W - MARGIN, cy + 730))
    draw.text((MARGIN + left_w + 40, cy + 18), "如果拿去讲，我建议这样收尾", font=FONT_H3, fill=TEXT)
    panel(draw, (MARGIN + left_w + 40, cy + 70, PAGE_W - MARGIN - 20, cy + 214), fill=TEAL_SOFT, radius=24)
    quote = "我们做的不是一个 tracking demo，而是一套让机器人把‘看见世界’和‘理解任务’接起来的 embodied agent runtime。"
    draw_text(draw, quote, x=MARGIN + left_w + 62, y=cy + 110, fnt=FONT_BODY, fill=TEXT, max_width=500, gap=8)
    y = cy + 238
    for title, body, fill in [
        ("先讲问题", "普通 tracking demo 只能框人，不能形成持续任务闭环。", ORANGE_SOFT),
        ("再讲架构", "perception 常驻、runner 单轮处理、session 单源、skills 插拔、viewer 只读。", NAVY_SOFT),
        ("最后讲价值", "这不是一次性脚本堆叠，而是一套可以继续长能力的 embodied agent kernel。", TEAL_SOFT),
    ]:
        h = card(draw, x=MARGIN + left_w + 40, y=y, w=500, title=title, body=body, fill=fill)
        y += h + 12

    lower_y = cy + 760
    panel(draw, (MARGIN, lower_y, PAGE_W - MARGIN, PAGE_H - 100), fill=PANEL)
    draw.text((MARGIN + 24, lower_y + 18), "最后压缩成五个关键词", font=FONT_H3, fill=TEXT)
    px = MARGIN + 24
    for label in ["持续感知", "单轮决策主链", "单一状态真相源", "能力可插拔", "系统可观察"]:
        pw = pill(draw, x=px, y=lower_y + 64, text=label)
        px += pw + 12
    summary = "这五个词，基本就是这套 embodied agent 技术方案的骨架。也是你讲完之后，听众应该带走的记忆点。"
    draw_text(draw, summary, x=MARGIN + 24, y=lower_y + 124, fnt=FONT_BODY, fill=MUTED, max_width=1070, gap=8)

    footer(draw, 6, 6)
    return Page(image)


def main():
    pages: Sequence[Page] = [page1(), page2(), page3(), page4(), page5(), page6()]
    images = [p.image.convert("RGB") for p in pages]
    images[0].save(OUTPUT_PDF, "PDF", resolution=150.0, save_all=True, append_images=images[1:])
    print(f"wrote {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
