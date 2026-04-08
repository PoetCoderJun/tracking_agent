# backend package layout

`backend/` 现在是 chat-first 的机器人 agent kernel，本身包含：

- `perception/`: 独立 perception service 接口、抽帧工具、perception bundle、CLI 查询接口。
- `tracking/`: tracking 的确定性工具、上下文构造与唯一 `loop` runner。
- `persistence/`: 单一 `session.json` 主状态与相关 save/load。
- `actions/`: CLI 动作执行接口。
- `cli.py`: 本地唯一主入口。
- `tests/`: 后端测试和 fixtures。

导入约定：

- `skills/` 负责技能定义与 skill 专属脚本。
- `backend/` 只保留 perception、runner、持久化、文件读写和唯一的本地 chat CLI。
- agent-owned state 统一持久化在 `session.json`，不再把 `agent_memory.json` 当成主真相源。
- perception service 独立运行，只通过共享存储写 observation，不通过 runtime API 注入。
- runtime 只读取 perception 已落盘的数据，不拥有 perception loop。
- tracking 只保留 `backend.tracking.loop` 这一条 runner 路径，不再保留独立 service 包装层或 detached rewrite worker。
- perception CLI 负责把感知快照暴露成 runner 易于读取的命令行接口。
- 若需要 skill 专属 perception writer、loop 或 query-plan 脚本，应放在对应 `skills/<skill>/scripts/`。
- 新代码统一从 `agent`、`backend.perception`、`backend.tracking`、`backend.persistence`、`backend.actions`、`backend.cli` 和 `viewer` 导入。
