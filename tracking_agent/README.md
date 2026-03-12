# tracking_agent package layout

`tracking_agent/` 现在按职责分为两层：

- `core/`: 会话状态、意图路由、单步追踪、会话循环。
- 根目录其它模块: DashScope 后端、推理工具、query-plan、图像处理与配置。

兼容性说明：

- 旧路径 `tracking_agent.pi_agent_core`、`tracking_agent.pi_agent_loop`、`tracking_agent.session_store`、`tracking_agent.intent_router` 仍可导入。
- 新代码优先从 `tracking_agent.core` 导入核心编排逻辑。
