#!/usr/bin/env node

import { execFile } from "node:child_process";
import process from "node:process";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";

const execFileAsync = promisify(execFile);

function printHelp() {
  process.stdout.write(
    [
      "Usage: node terminal/pi_agent_tui.mjs [options]",
      "",
      "Required options:",
      "  --python <path>",
      "  --repo-root <path>",
      "  --session-id <id>",
      "  --device-id <id>",
      "  --state-root <path>",
      "  --artifacts-root <path>",
      "  --env-file <path>",
      "  --pi-binary <name>",
      "  --frame-buffer-size <n>",
      "",
      "Optional repeatable options:",
      "  --pi-timeout-seconds <n>",
      "  --available-skill <name>",
      "  --enabled-skill <name>",
      "",
    ].join("\n"),
  );
}

function parseArgs(argv) {
  const config = {
    python: "",
    repoRoot: "",
    sessionId: "",
    deviceId: "",
    stateRoot: "",
    artifactsRoot: "",
    envFile: "",
    piBinary: "",
    frameBufferSize: "",
    piTimeoutSeconds: "",
    availableSkills: [],
    enabledSkills: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      config.help = true;
      continue;
    }

    const value = argv[index + 1];
    if (value === undefined) {
      throw new Error(`Missing value for ${arg}`);
    }

    switch (arg) {
      case "--python":
        config.python = value;
        break;
      case "--repo-root":
        config.repoRoot = value;
        break;
      case "--session-id":
        config.sessionId = value;
        break;
      case "--device-id":
        config.deviceId = value;
        break;
      case "--state-root":
        config.stateRoot = value;
        break;
      case "--artifacts-root":
        config.artifactsRoot = value;
        break;
      case "--env-file":
        config.envFile = value;
        break;
      case "--pi-binary":
        config.piBinary = value;
        break;
      case "--frame-buffer-size":
        config.frameBufferSize = value;
        break;
      case "--pi-timeout-seconds":
        config.piTimeoutSeconds = value;
        break;
      case "--available-skill":
        config.availableSkills.push(value);
        break;
      case "--enabled-skill":
        config.enabledSkills.push(value);
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
    index += 1;
  }

  if (config.help) {
    return config;
  }

  for (const fieldName of [
    "python",
    "repoRoot",
    "sessionId",
    "deviceId",
    "stateRoot",
    "artifactsRoot",
    "envFile",
    "piBinary",
    "frameBufferSize",
  ]) {
    if (!String(config[fieldName] || "").trim()) {
      throw new Error(`Missing required argument: --${fieldName.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)}`);
    }
  }

  return config;
}

async function runChatTurn(config, text) {
  const args = [
    "-m",
    "backend.cli",
    "chat",
    "--session-id",
    config.sessionId,
    "--text",
    text,
    "--device-id",
    config.deviceId,
    "--state-root",
    config.stateRoot,
    "--frame-buffer-size",
    config.frameBufferSize,
    "--env-file",
    config.envFile,
    "--artifacts-root",
    config.artifactsRoot,
    "--pi-binary",
    config.piBinary,
  ];
  if (config.piTimeoutSeconds) {
    args.push("--pi-timeout-seconds", config.piTimeoutSeconds);
  }

  try {
    const { stdout } = await execFileAsync(config.python, args, {
      cwd: config.repoRoot,
      env: process.env,
      maxBuffer: 16 * 1024 * 1024,
      encoding: "utf8",
    });
    const lines = stdout
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) {
      throw new Error("robot-agent chat returned no JSON payload.");
    }
    return JSON.parse(lines[lines.length - 1]);
  } catch (error) {
    const stderr = String(error?.stderr || "").trim();
    const stdout = String(error?.stdout || "").trim();
    const message = stderr || stdout || String(error?.message || error);
    throw new Error(message);
  }
}

function resolveReplyText(payload) {
  const sessionResult = payload?.session_result;
  if (sessionResult && typeof sessionResult === "object") {
    const text = String(sessionResult.text || "").trim();
    if (text) {
      return text;
    }
  }

  const reason = String(payload?.reason || "").trim();
  if (reason) {
    return reason;
  }

  const skillName = String(payload?.skill_name || "").trim();
  if (skillName) {
    return skillName;
  }

  return "(empty reply)";
}

function describeStatus(config) {
  const enabled = config.enabledSkills.length > 0 ? config.enabledSkills.join(", ") : "(none)";
  const available = config.availableSkills.length > 0 ? config.availableSkills.join(", ") : "(none)";
  return `session_id=${config.sessionId}\nenabled_skills=${enabled}\navailable_skills=${available}`;
}

function helpText() {
  return [
    "/help      show this message",
    "/status    show current session and enabled skills",
    "/quit      exit the terminal",
    "/q         exit the terminal",
    "",
    "Any other input is sent as a chat turn.",
  ].join("\n");
}

async function runInteractive(config) {
  let piTui;
  try {
    piTui = await import("@mariozechner/pi-tui");
  } catch (error) {
    throw new Error(
      `Missing PI TUI dependencies. Run \`cd terminal && npm install\` first.\n${String(error?.message || error)}`,
    );
  }

  const {
    CombinedAutocompleteProvider,
    Container,
    Editor,
    Key,
    Loader,
    ProcessTerminal,
    Spacer,
    TUI,
    Text,
    matchesKey,
  } = piTui;

  const terminal = new ProcessTerminal();
  terminal.setTitle(`robot-agent ${config.sessionId}`);
  const tui = new TUI(terminal, true);

  const rootMessages = new Container();
  const busyArea = new Container();
  tui.addChild(rootMessages);
  tui.addChild(busyArea);
  tui.addChild(new Spacer(1));

  const editorTheme = {
    borderColor: (value) => value,
    selectList: {
      selectedPrefix: (value) => value,
      selectedText: (value) => value,
      description: (value) => value,
      scrollInfo: (value) => value,
      noMatch: (value) => value,
    },
  };
  const editor = new Editor(tui, editorTheme, {
    paddingX: 1,
    autocompleteMaxVisible: 8,
  });
  editor.setAutocompleteProvider(
    new CombinedAutocompleteProvider(
      [
        { name: "help", description: "Show available REPL commands" },
        { name: "status", description: "Show current session and skills" },
        { name: "quit", description: "Exit the terminal" },
        { name: "q", description: "Exit the terminal" },
      ],
      config.repoRoot,
    ),
  );
  tui.addChild(editor);
  tui.setFocus(editor);

  function appendBubble(kind, title, body) {
    const safeBody = String(body || "").trim() || "(empty)";
    const prefix = kind === "error" ? "[error]" : kind === "system" ? "[system]" : "";
    const header = prefix ? `${prefix} ${title}` : title;
    rootMessages.addChild(new Text(`${header}\n${safeBody}`, 0, 0));
    rootMessages.addChild(new Spacer(1));
    tui.requestRender();
  }

  let loader = null;
  function setBusy(message) {
    if (loader) {
      loader.stop();
      loader = null;
    }
    busyArea.clear();
    if (message) {
      busyArea.addChild(new Spacer(1));
      loader = new Loader(
        tui,
        (value) => value,
        (value) => value,
        message,
      );
      busyArea.addChild(loader);
      loader.start();
    }
    tui.requestRender();
  }

  let shuttingDown = false;
  let resolveExit = null;
  const exitPromise = new Promise((resolve) => {
    resolveExit = resolve;
  });

  function shutdown(code = 0) {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    setBusy(null);
    try {
      tui.stop();
    } finally {
      resolveExit?.(code);
    }
  }

  async function handleCommand(text) {
    const normalized = text.trim().toLowerCase();
    if (normalized === "/help") {
      appendBubble("system", "Commands", helpText());
      return true;
    }
    if (normalized === "/status") {
      appendBubble("system", "Status", describeStatus(config));
      return true;
    }
    if (normalized === "/quit" || normalized === "/q" || normalized === "/exit") {
      shutdown(0);
      return true;
    }
    if (normalized.startsWith("/")) {
      appendBubble("error", "Command Error", "Unknown command. Use /help.");
      return true;
    }
    return false;
  }

  editor.onSubmit = async (value) => {
    const text = String(value || "").trim();
    if (!text) {
      return;
    }
    if (await handleCommand(text)) {
      editor.setText("");
      return;
    }

    editor.disableSubmit = true;
    editor.addToHistory?.(text);
    editor.setText("");
    appendBubble("user", "You", text);
    setBusy("Pi is processing...");

    try {
      const payload = await runChatTurn(config, text);
      const skillName = String(payload?.skill_name || "").trim();
      const title = skillName ? `Pi · ${skillName}` : "Pi";
      appendBubble("assistant", title, resolveReplyText(payload));
    } catch (error) {
      appendBubble(
        "error",
        "Turn Failed",
        `${String(error?.message || error)}\n\nIf this is a timeout, retry with --pi-timeout-seconds 180.`,
      );
    } finally {
      setBusy(null);
      editor.disableSubmit = false;
      tui.setFocus(editor);
      tui.requestRender();
    }
  };

  tui.addInputListener((data) => {
    if (matchesKey(data, Key.ctrl("c"))) {
      shutdown(0);
      return { consume: true };
    }
    return undefined;
  });
  process.once("SIGINT", () => shutdown(0));
  process.once("SIGTERM", () => shutdown(0));

  appendBubble(
    "system",
    "Robot Agent",
    `session=${config.sessionId}\ncommands=/help /status /quit\nskills=${config.enabledSkills.join(", ") || "(none)"}`,
  );

  tui.start();
  return await exitPromise;
}

export async function main(argv = process.argv.slice(2)) {
  let config;
  try {
    config = parseArgs(argv);
  } catch (error) {
    process.stderr.write(`${String(error?.message || error)}\n`);
    printHelp();
    return 1;
  }

  if (config.help) {
    printHelp();
    return 0;
  }

  try {
    return await runInteractive(config);
  } catch (error) {
    process.stderr.write(`${String(error?.message || error)}\n`);
    return 1;
  }
}

const entryArg = process.argv[1];
if (entryArg && import.meta.url === pathToFileURL(entryArg).href) {
  const exitCode = await main();
  process.exit(exitCode);
}
