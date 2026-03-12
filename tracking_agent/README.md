# tracking_agent package layout

`tracking_agent/` 现在按职责分为三组：

- `core/`: session 存储与 runtime state 存储。
- `pipeline/`: 抽帧、query plan、历史 batch 读取。
- 根目录保留通用模块: 图像处理、memory 格式、配置、输出校验。

导入约定：

- `skills/` 负责开放式的 tracking 会话编排，而不是做封闭意图分类。
- Python 代码只保留 timing、状态、文件读写和结果校验等底层工具。
- 若需要端到端回放，只能放在测试 harness 中，不能作为生产 workflow 入口。
- 新代码统一从 `tracking_agent.core`、`tracking_agent.pipeline` 和根目录工具模块导入。
