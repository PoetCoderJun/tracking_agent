const pptxgen = require("pptxgenjs");
const {
  autoFontSize,
  imageSizingContain,
  warnIfSlideHasOverlaps,
  warnIfSlideElementsOutOfBounds,
} = require("./pptxgenjs_helpers");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "Codex";
pptx.company = "OpenAI";
pptx.subject = "Tracking Agent Weekly Report";
pptx.title = "Tracking Agent Weekly Report";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "PingFang SC",
  bodyFontFace: "PingFang SC",
  lang: "zh-CN",
};

const W = 13.333;
const H = 7.5;

const C = {
  bg: "F7FAFC",
  white: "FFFFFF",
  ink: "16324F",
  sub: "55697B",
  line: "D7E2EA",
  green: "2C8C68",
  greenSoft: "E8F4EF",
  blue: "2F6FAA",
  blueSoft: "EAF2FB",
  orange: "C96B2C",
  sand: "F8F2E8",
  red: "B94E59",
  rose: "F8ECEF",
  dark: "102A43",
};

function addBg(slide) {
  slide.background = { color: C.bg };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: W,
    h: H,
    line: { color: C.bg, transparency: 100 },
    fill: { color: C.bg },
  });
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.44,
    y: 0.36,
    w: 0.14,
    h: 6.78,
    line: { color: C.green, transparency: 100 },
    fill: { color: C.green },
  });
}

function addTitle(slide, pageNo, title, subtitle) {
  slide.addText(
    title,
    autoFontSize(title, "PingFang SC", {
      x: 0.88,
      y: 0.42,
      w: 7.8,
      h: 0.46,
      minFontSize: 22,
      maxFontSize: 28,
      fontSize: 28,
      bold: true,
      color: C.ink,
      margin: 0,
      valign: "mid",
    })
  );
  slide.addText(subtitle, {
    x: 0.9,
    y: 1.02,
    w: 9.4,
    h: 0.24,
    fontFace: "PingFang SC",
    fontSize: 10.5,
    color: C.sub,
    margin: 0,
  });
  slide.addText(`0${pageNo}`, {
    x: 11.95,
    y: 0.45,
    w: 0.65,
    h: 0.3,
    fontFace: "PingFang SC",
    fontSize: 18,
    bold: true,
    color: C.green,
    align: "right",
    margin: 0,
  });
  slide.addShape(pptx.ShapeType.line, {
    x: 0.9,
    y: 1.37,
    w: 11.8,
    h: 0,
    line: { color: C.line, width: 1.1 },
  });
}

function addCard(slide, x, y, w, h, fill = C.white, lineColor = C.line) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.08,
    line: { color: lineColor, width: 1 },
    fill: { color: fill },
    shadow: {
      type: "outer",
      color: "C7D2DC",
      blur: 1,
      angle: 45,
      distance: 1,
      opacity: 0.08,
    },
  });
}

function addSectionLabel(slide, text, x, y, color = C.ink) {
  slide.addText(text, {
    x,
    y,
    w: 2.4,
    h: 0.24,
    fontFace: "PingFang SC",
    fontSize: 15,
    bold: true,
    color,
    margin: 0,
  });
}

function addBullets(slide, items, x, y, w, options = {}) {
  const rowH = options.rowH || 0.48;
  const gap = options.gap || 0.12;
  const fs = options.fontSize || 14.5;
  const bulletColor = options.bulletColor || C.green;
  items.forEach((item, i) => {
    const yy = y + i * (rowH + gap);
    slide.addShape(pptx.ShapeType.roundRect, {
      x,
      y: yy + 0.16,
      w: 0.09,
      h: 0.09,
      rectRadius: 0.02,
      line: { color: bulletColor, transparency: 100 },
      fill: { color: bulletColor },
    });
    slide.addText(item, {
      x: x + 0.18,
      y: yy,
      w: w - 0.18,
      h: rowH,
      fontFace: "PingFang SC",
      fontSize: fs,
      color: C.dark,
      margin: 0,
      valign: "mid",
    });
  });
}

function addPill(slide, text, x, y, w, fill, color) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h: 0.34,
    rectRadius: 0.12,
    line: { color: fill, transparency: 100 },
    fill: { color: fill },
  });
  slide.addText(text, {
    x,
    y: y + 0.03,
    w,
    h: 0.24,
    fontFace: "PingFang SC",
    fontSize: 10,
    bold: true,
    color,
    align: "center",
    margin: 0,
  });
}

function addImageCard(slide, path, x, y, w, h, title, subtitle) {
  addCard(slide, x, y, w, h, C.white, C.line);
  slide.addImage({
    path,
    ...imageSizingContain(path, x + 0.12, y + 0.12, w - 0.24, h - 0.68),
  });
  slide.addText(title, {
    x: x + 0.14,
    y: y + h - 0.48,
    w: w - 0.28,
    h: 0.16,
    fontFace: "PingFang SC",
    fontSize: 11.5,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  slide.addText(subtitle, {
    x: x + 0.16,
    y: y + h - 0.28,
    w: w - 0.32,
    h: 0.12,
    fontFace: "PingFang SC",
    fontSize: 8.6,
    color: C.sub,
    align: "center",
    margin: 0,
  });
}

function finalize(slide, options = {}) {
  if (!options.skipOverlapCheck) {
    warnIfSlideHasOverlaps(slide, pptx);
  }
  warnIfSlideElementsOutOfBounds(slide, pptx);
}

function slide1() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, 1, "问题不在“看见谁”，而在“持续跟住同一个人”", "传统 tracking 能解决短时连续性，但机器人场景里真正困难的是长期目标一致性");

  addSectionLabel(slide, "为什么传统方案不够", 0.95, 1.72);
  addBullets(
    slide,
    [
      "MOT / tracking 擅长高频推理和中短期连续跟随",
      "遇到遮挡、离场重现、相似目标时，容易出现 ID 丢失或漂移",
      "ReID 本质仍是外观特征相似度匹配，不是真正的语义身份理解",
      "ReID 多基于监控视角训练，迁移到机器人视角后域偏移明显",
    ],
    0.96,
    2.05,
    6.0,
    { fontSize: 15, rowH: 0.48, gap: 0.12 }
  );

  addCard(slide, 7.35, 1.82, 2.28, 1.42, C.greenSoft, "B8DDCE");
  slide.addText("传统 tracking 的强项", {
    x: 7.56,
    y: 2.0,
    w: 1.86,
    h: 0.22,
    fontFace: "PingFang SC",
    fontSize: 15,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  slide.addText("高频\n低延迟\n短时稳定", {
    x: 7.83,
    y: 2.35,
    w: 1.32,
    h: 0.56,
    fontFace: "PingFang SC",
    fontSize: 12.5,
    color: C.dark,
    align: "center",
    margin: 0,
  });

  addCard(slide, 9.86, 1.82, 2.28, 1.42, C.sand, "E4D0A6");
  slide.addText("长期跟随的难点", {
    x: 10.06,
    y: 2.0,
    w: 1.88,
    h: 0.22,
    fontFace: "PingFang SC",
    fontSize: 15,
    bold: true,
    color: C.ink,
    align: "center",
    margin: 0,
  });
  slide.addText("丢失后重找\n换 ID 后重绑定\n跟错后的纠正", {
    x: 10.2,
    y: 2.35,
    w: 1.62,
    h: 0.56,
    fontFace: "PingFang SC",
    fontSize: 12.2,
    color: C.dark,
    align: "center",
    margin: 0,
  });

  addCard(slide, 7.35, 3.58, 4.79, 1.6, C.rose, "E6C7CF");
  slide.addText("所以这个项目的切入点不是替代检测器，而是补上“长期语义一致性”。", {
    x: 7.7,
    y: 3.92,
    w: 4.08,
    h: 0.26,
    fontFace: "PingFang SC",
    fontSize: 15,
    bold: true,
    color: C.red,
    align: "center",
    margin: 0,
  });
  slide.addText("把“该跟谁”从纯视觉匹配问题，升级成 Agent 驱动的持续决策问题。", {
    x: 7.76,
    y: 4.28,
    w: 3.96,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 12.8,
    color: C.dark,
    align: "center",
    margin: 0,
  });

  addCard(slide, 0.96, 5.55, 11.2, 0.92, C.white, C.orange);
  slide.addText("一句话：ReID + tracking 解决的是“短期不丢”，Tracking Agent 要解决的是“长期知道自己在跟谁”。", {
    x: 1.35,
    y: 5.87,
    w: 10.4,
    h: 0.22,
    fontFace: "PingFang SC",
    fontSize: 15,
    bold: true,
    color: C.orange,
    align: "center",
    margin: 0,
  });

  // Intentional text-on-card layout; the generic overlap checker reports false positives here.
  finalize(slide, { skipOverlapCheck: true });
}

function slide2() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, 2, "项目效果：不是只找到人，而是能持续跟住并持续记住", "录屏里最能说明亮点的部分，是目标 ID 的持续一致性和右下角 Agent memory 的历史改写");

  addPill(slide, "同一目标 ID = 6", 0.96, 1.66, 1.35, C.greenSoft, C.green);
  addPill(slide, "场景切换：走廊 -> 狭窄通道 -> 电梯", 2.48, 1.66, 2.8, C.blueSoft, C.blue);
  addPill(slide, "memory 持续改写", 5.48, 1.66, 1.48, C.rose, C.red);

  addImageCard(
    slide,
    "assets/frame_004_live_crop.jpg",
    0.95,
    2.12,
    3.65,
    1.95,
    "初始化",
    "多人候选中先完成目标绑定"
  );
  addImageCard(
    slide,
    "assets/frame_011_live_crop.jpg",
    4.84,
    2.12,
    3.65,
    1.95,
    "继续跟随",
    "进入更窄、更难分辨的场景"
  );
  addImageCard(
    slide,
    "assets/frame_017_live_crop.jpg",
    8.73,
    2.12,
    3.65,
    1.95,
    "复杂反光环境",
    "在电梯中继续保持同一目标"
  );

  addImageCard(
    slide,
    "assets/frame_004_memory_crop.jpg",
    0.95,
    4.3,
    3.65,
    1.72,
    "Memory 1",
    "初始阶段偏外观描述"
  );
  addImageCard(
    slide,
    "assets/frame_011_memory_crop.jpg",
    4.84,
    4.3,
    3.65,
    1.72,
    "Memory 2",
    "开始强调当前场景下的区分线索"
  );
  addImageCard(
    slide,
    "assets/frame_017_memory_crop.jpg",
    8.73,
    4.3,
    3.65,
    1.72,
    "Memory 3",
    "进入电梯后继续刷新稳定特征和干扰项"
  );

  addCard(slide, 1.08, 6.28, 11.04, 0.72, C.greenSoft, "B8DDCE");
  slide.addText("这页想证明的不是 UI，而是效果：目标在跨场景连续跟随时，Agent 会把“当前应该怎么认这个人”持续沉淀成 memory。", {
    x: 1.42,
    y: 6.51,
    w: 10.35,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 13.6,
    bold: true,
    color: C.green,
    align: "center",
    margin: 0,
  });

  // Intentional text-on-card layout; the generic overlap checker reports false positives here.
  finalize(slide, { skipOverlapCheck: true });
}

function slide3() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, 3, "核心机制：Robot 给候选，Agent 决定“当前该跟谁”", "前后端和 Robot 端都不是重点；重点是 Agent 如何利用候选框、memory 和会话上下文做语义绑定");

  addCard(slide, 0.95, 1.9, 3.45, 3.5, C.white, C.line);
  addSectionLabel(slide, "Robot 侧输入", 1.18, 2.12);
  addBullets(
    slide,
    [
      "图像 / 当前帧",
      "bbox、track_id、score",
      "session_id、frame_id、timestamp",
      "用户文本：初始化描述或继续跟踪",
    ],
    1.18,
    2.45,
    2.9,
    { fontSize: 14.2, rowH: 0.44, gap: 0.1 }
  );
  slide.addText("这里只模拟 robot 环境，不在端上做复杂决策。", {
    x: 1.18,
    y: 4.9,
    w: 2.85,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 10.8,
    color: C.sub,
    margin: 0,
  });

  addCard(slide, 4.94, 1.72, 3.45, 3.86, C.blueSoft, "C9DDF2");
  addSectionLabel(slide, "Tracking Agent", 5.18, 1.98);
  addPill(slide, "init", 5.18, 2.34, 0.7, C.white, C.blue);
  addPill(slide, "track", 5.95, 2.34, 0.78, C.white, C.blue);
  addPill(slide, "rewrite_memory", 6.81, 2.34, 1.35, C.white, C.blue);
  addBullets(
    slide,
    [
      "初始化：在候选框中完成首次目标绑定",
      "持续跟随：从 memory + 历史确认帧中继续找人",
      "目标不确定时，不强猜，而是反问或返回 missing",
      "跟踪成功后，重写一段更适合下一轮搜索的 memory",
    ],
    5.18,
    2.85,
    2.95,
    { fontSize: 13.8, rowH: 0.44, gap: 0.1, bulletColor: C.blue }
  );

  addCard(slide, 8.93, 1.9, 3.45, 3.5, C.white, C.line);
  addSectionLabel(slide, "对下游的输出", 9.16, 2.12);
  addBullets(
    slide,
    [
      "当前选中的目标 ID",
      "found / missing / clarify",
      "面向用户的解释或追问",
      "更新后的 tracking memory",
    ],
    9.16,
    2.45,
    2.9,
    { fontSize: 14.2, rowH: 0.44, gap: 0.1, bulletColor: C.orange }
  );
  slide.addText("跟错了可纠正，跟丢了可重找，不被旧 track_id 绑死。", {
    x: 9.16,
    y: 4.9,
    w: 2.85,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 10.8,
    color: C.sub,
    margin: 0,
  });

  slide.addShape(pptx.ShapeType.chevron, {
    x: 4.58,
    y: 3.36,
    w: 0.22,
    h: 0.34,
    line: { color: C.green, transparency: 100 },
    fill: { color: C.green },
  });
  slide.addShape(pptx.ShapeType.chevron, {
    x: 8.57,
    y: 3.36,
    w: 0.22,
    h: 0.34,
    line: { color: C.green, transparency: 100 },
    fill: { color: C.green },
  });

  addCard(slide, 1.36, 6.02, 10.5, 0.72, C.white, C.green);
  slide.addText("系统边界很清晰：下游解决“看见谁”，上游 Agent 解决“该跟谁”。", {
    x: 1.66,
    y: 6.25,
    w: 9.9,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 14.2,
    bold: true,
    color: C.green,
    align: "center",
    margin: 0,
  });

  finalize(slide);
}

function slide4() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, 4, "为什么必须是 Agent，而不是 ReID + 一套规则", "这个项目的关键增量，不是多一个模型，而是把跟踪做成一个可持续会话、可纠错、可扩展的 Agent");

  addCard(slide, 0.95, 1.82, 5.5, 4.25, C.white, C.line);
  addSectionLabel(slide, "传统方案 vs Tracking Agent", 1.18, 2.04);

  const rows = [
    ["信息来源", "外观特征 + 局部轨迹", "图像 + 候选框 + memory + 对话上下文"],
    ["目标绑定", "偏一次性匹配", "持续语义绑定"],
    ["错误恢复", "规则补丁多，长尾难收", "可纠错、可重找、可反问"],
    ["可扩展性", "每加能力都要改 workflow", "新增 skill 即可扩能力"],
  ];

  let yy = 2.46;
  rows.forEach((row, idx) => {
    const fill = idx % 2 === 0 ? C.bg : C.white;
    slide.addShape(pptx.ShapeType.rect, {
      x: 1.16,
      y: yy,
      w: 5.06,
      h: 0.72,
      line: { color: C.line, width: 0.6 },
      fill: { color: fill },
    });
    slide.addText(row[0], {
      x: 1.28,
      y: yy + 0.2,
      w: 0.76,
      h: 0.14,
      fontFace: "PingFang SC",
      fontSize: 11.2,
      bold: true,
      color: C.ink,
      margin: 0,
      align: "center",
    });
    slide.addText(row[1], {
      x: 2.15,
      y: yy + 0.17,
      w: 1.35,
      h: 0.18,
      fontFace: "PingFang SC",
      fontSize: 10.5,
      color: C.dark,
      margin: 0,
      align: "center",
    });
    slide.addText(row[2], {
      x: 3.7,
      y: yy + 0.17,
      w: 2.3,
      h: 0.18,
      fontFace: "PingFang SC",
      fontSize: 10.5,
      color: C.dark,
      margin: 0,
      align: "center",
    });
    yy += 0.72;
  });

  addCard(slide, 6.9, 1.82, 5.45, 1.7, C.greenSoft, "B8DDCE");
  addSectionLabel(slide, "纯 Agent / skills 形态", 7.16, 2.04, C.green);
  addPill(slide, "reply", 7.16, 2.38, 0.82, C.white, C.green);
  addPill(slide, "init", 8.06, 2.38, 0.68, C.white, C.green);
  addPill(slide, "track", 8.82, 2.38, 0.8, C.white, C.green);
  addPill(slide, "rewrite_memory", 9.7, 2.38, 1.54, C.white, C.green);
  slide.addText("Host Agent 按上下文选择 skill，而不是走写死的显式 workflow。", {
    x: 7.16,
    y: 2.86,
    w: 4.9,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 12.8,
    color: C.dark,
    margin: 0,
    align: "center",
  });

  addCard(slide, 6.9, 3.74, 5.45, 1.54, C.blueSoft, "C9DDF2");
  addSectionLabel(slide, "Pi 思路为什么契合", 7.16, 3.95, C.blue);
  addBullets(
    slide,
    [
      "内核尽量小，复杂能力通过 skills / extensions 长出来",
      "session 天然承载状态，适合这种持续会话式跟踪任务",
      "新增能力时优先加 skill，而不是重写主流程",
    ],
    7.16,
    4.24,
    4.85,
    { fontSize: 12.6, rowH: 0.34, gap: 0.06, bulletColor: C.blue }
  );

  // Intentional text-on-card layout; the generic overlap checker reports false positives here.
  finalize(slide, { skipOverlapCheck: true });
}

function slide5() {
  const slide = pptx.addSlide();
  addBg(slide);
  addTitle(slide, 5, "项目价值 / 下一步", "这个项目证明了 Tracking 可以从“纯视觉模块”演化成“可解释、可交互、可持续优化的 Agent 能力”");

  addCard(slide, 0.95, 1.88, 3.55, 3.65, C.white, C.line);
  addSectionLabel(slide, "已经体现出的价值", 1.18, 2.1);
  addBullets(
    slide,
    [
      "跨场景持续跟随，而不是只在单一视角下稳定",
      "memory 会被持续改写，不是一次性描述",
      "结果可解释，能回答“为什么还是这个人”",
    ],
    1.18,
    2.44,
    3.05,
    { fontSize: 13.8, rowH: 0.44, gap: 0.1 }
  );

  addCard(slide, 4.89, 1.88, 3.55, 3.65, C.white, C.line);
  addSectionLabel(slide, "对系统的意义", 5.12, 2.1);
  addBullets(
    slide,
    [
      "降低长期跟随里的错跟和丢跟成本",
      "让“纠正”和“重找”成为标准能力，不是异常处理",
      "为持续对话式跟随打下统一范式",
    ],
    5.12,
    2.44,
    3.05,
    { fontSize: 13.8, rowH: 0.44, gap: 0.1, bulletColor: C.blue }
  );

  addCard(slide, 8.83, 1.88, 3.55, 3.65, C.white, C.line);
  addSectionLabel(slide, "下一步", 9.06, 2.1);
  addBullets(
    slide,
    [
      "引入更多端侧证据：轨迹、姿态、轻量 embedding",
      "增强长时间丢失后的主动重找能力",
      "扩展到跨场景 / 跨 camera / 任务级持续跟随",
    ],
    9.06,
    2.44,
    3.05,
    { fontSize: 13.8, rowH: 0.44, gap: 0.1, bulletColor: C.orange }
  );

  addCard(slide, 1.18, 5.88, 10.95, 0.86, C.green, C.green);
  slide.addText("最后一句话：我们保留传统 tracking 的速度，把长期目标一致性、记忆、解释和纠错交给 Agent。", {
    x: 1.55,
    y: 6.18,
    w: 10.2,
    h: 0.18,
    fontFace: "PingFang SC",
    fontSize: 15,
    bold: true,
    color: C.white,
    align: "center",
    margin: 0,
  });

  finalize(slide);
}

async function main() {
  slide1();
  slide2();
  slide3();
  slide4();
  slide5();

  await pptx.writeFile({ fileName: "tracking_agent_weekly_report.pptx" });
  console.log("Wrote tracking_agent_weekly_report.pptx");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
