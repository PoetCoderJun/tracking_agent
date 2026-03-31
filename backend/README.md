# backend package layout

`backend/` 现在是通用机器人 agent runtime，本身包含：

- `perception/`: 独立 perception service 接口、抽帧工具、perception bundle、CLI 查询接口。
- `agent/`: context、memory、runtime、query plan、Pi CLI wrapper。
- `persistence/`: live session、runtime 进度和通用产物的 save/load。
- `actions/`: CLI 动作执行接口。
- `cli.py`: 本地唯一主入口。
- `tests/`: 后端测试和 fixtures。

导入约定：

- `skills/` 负责技能定义与 skill 专属脚本。
- `backend/` 只保留 runtime、持久化、文件读写和唯一的本地 chat CLI。
- `context` 和 `memory` 的所有权在 `backend/agent/`，不是在 `backend/persistence/`。
- perception service 独立运行，只通过共享存储写 observation，不通过 runtime API 注入。
- runtime 只读取 perception 已落盘的数据，不拥有 perception loop。
- perception CLI 负责把感知快照暴露成 Pi 易于读取的命令行接口。
- 若需要 skill 专属 perception writer、loop 或 query-plan 脚本，应放在对应 `skills/<skill>/scripts/`。
- 新代码统一从 `backend.perception`、`backend.agent`、`backend.persistence`、`backend.actions`、`backend.cli` 和根目录工具模块导入。
