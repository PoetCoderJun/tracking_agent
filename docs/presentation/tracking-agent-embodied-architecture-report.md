# Tracking Agent Embodied Architecture Report

副标题：面向项目汇报的 embodied agent 技术方案架构说明  
版本：基于仓库实态检查整理  
检查日期：2026-04-02

## 1. 项目目标与问题定义

`tracking_agent` 的核心目标不是单纯做一个 tracking demo，而是把“持续感知 + 对话驱动决策 + 可插拔能力”收敛成一个可运行在 robot / Pi 侧的 embodied agent kernel。

这个项目要解决的不是单点算法问题，而是一个系统问题：

- 机器人需要持续看到世界，但不能让 perception loop 反客为主，吞掉整个 runtime。
- agent 需要保持多轮对话上下文和当前世界状态的一致性，不能在多个 memory/store 之间来回漂移。
- tracking、speech、以及后续能力都应该是 capability module，而不是每加一个 skill 就改造一遍 backend 主干。
- 展示层需要能实时看到 agent 当前状态，但又不能把 viewer 前端强耦合进主执行链路。

因此，仓库当前的真实架构重点是：**chat-first、perception 常驻、单 runner 主链、单一 session truth、skill 插拔化**。

## 2. 架构原则

仓库文档与代码实现体现出一组非常明确的设计原则：

- **Chat-first, not perception-first**：agent turn 由聊天、脚本或 loop 事件触发；perception 负责提供当前世界上下文，但不主导高层决策。
- **Perception is the only always-on subsystem**：只有 perception 服务持续运行并写入 observation。
- **Single runner path**：所有 turn 最终都归并到 `PiAgentRunner` 这一条主处理路径。
- **Single persisted session-state truth**：agent 自有状态以 `session.json` 为主真相源，避免并行 memory mirror。
- **Skills are ordinary capability modules**：`tracking`、`speech`、`web_search` 都通过统一 skill surface 接入。
- **Viewer is read-only presentation**：viewer 只消费状态，不参与执行闭环。

这些原则的意义在于：它们把系统从“tracking 专用 runtime”拉回到“通用 embodied agent kernel”。

## 3. 系统全景

从系统视角看，这个项目可以理解为三条相互配合但边界清晰的运行平面：

1. **Continuous Perception Plane**
   `scripts/run_tracking_perception.py` 持续读取摄像头或视频，做 person detection / tracking，并通过 `LocalPerceptionService` 把 observation 写入共享状态。

2. **Turn Orchestration Plane**
   用户输入、tracking continuation、或脚本事件进入 `backend/cli.py` / `PiAgentRunner`，由 runner 构造 turn context、选择 skill 路径，并落盘结果。

3. **Presentation Plane**
   `backend/agent_viewer_stream.py` 把 session + perception + skill viewer module 聚合成 websocket payload，`apps/tracking-viewer` 负责可视化展示。

高层结构可以抽象成：

```text
Camera / Video
    -> Perception Process
    -> perception snapshot.json + keyframes

User / Script / Tracking Loop
    -> backend/cli.py
    -> PiAgentRunner
    -> route_context + skill_context
    -> Pi or deterministic skill entry
    -> session.json / skill_cache / latest_result

session.json + perception snapshot.json
    -> viewer stream websocket
    -> tracking-viewer React app
```

## 4. 总体架构与层次关系

### 4.1 Context / Runtime View

```text
+---------------------------------------------------------------+
|                        Embodied Agent Kernel                  |
+---------------------------------------------------------------+
|  Trigger Layer                                                |
|  - robot-agent chat                                           |
|  - tracking loop                                              |
|  - manual scripts                                             |
+---------------------------------------------------------------+
|  Turn Orchestration Layer                                     |
|  - backend/cli.py                                             |
|  - backend/agent/runner.py                                    |
|  - backend/agent/pi_protocol.py                               |
|  - backend/agent/route_context.py                             |
+---------------------------------------------------------------+
|  State Layer                                                  |
|  - active_session.json                                        |
|  - sessions/<id>/session.json                                 |
|  - perception/sessions/<id>/snapshot.json                     |
+---------------------------------------------------------------+
|  Capability Layer                                             |
|  - skills/tracking                                            |
|  - skills/speech                                              |
|  - skills/web_search                                          |
+---------------------------------------------------------------+
|  Presentation Layer                                           |
|  - backend/agent_viewer_stream.py                             |
|  - apps/tracking-viewer                                       |
+---------------------------------------------------------------+
|  Continuous Perception Layer                                  |
|  - scripts/run_tracking_perception.py                         |
|  - backend/perception/service.py                              |
+---------------------------------------------------------------+
```

### 4.2 Why this matters

这套分层最重要的价值，不是“看起来整齐”，而是明确了谁负责持续运行、谁负责单轮决策、谁负责状态、谁只是显示。

## 5. 主要组件与职责

| 组件 | 代表路径 | 主要职责 | 在整体中的作用 |
| --- | --- | --- | --- |
| Perception Service | `backend/perception/` | 维护 observation window、保存 keyframe、生成 persisted snapshot、提供 CLI 读取接口 | 提供持续世界感知，但不做高层 orchestration |
| Agent Runner | `backend/agent/runner.py` | 接收 turn、构造 route context、调用 Pi 或 direct skill path、应用 payload 到 session | 系统唯一主处理链 |
| Pi Protocol | `backend/agent/pi_protocol.py` | 把 turn context、enabled skills、service commands 交给 Pi，并解析结构化输出 | 管理 reasoning plane 与本地 runtime 的边界 |
| Session Store / Persistence | `backend/persistence/` | 读写 `session.json`、维护 active session、合并 latest result / skill cache / perception cache | 保证单一状态真相源 |
| Skill Surface | `backend/skills.py` | discovery、route summary、turn context、direct init/turn、rewrite、viewer module 聚合 | 把能力扩展收敛到统一契约 |
| Tracking Skill | `skills/tracking/` | target init、continue tracking、memory rewrite、viewer module | 当前主力 embodied capability |
| Speech Skill | `skills/speech/` | TTS 生成能力示例 | 证明非 tracking 能力也可通过同一框架接入 |
| Web Search Skill | `skills/web_search/` | 外部信息检索示例 | 证明 skill 插拔边界不依赖 embodied-only 能力 |
| Viewer Stream | `backend/agent_viewer_stream.py` | 聚合 agent / observation / modules，输出 websocket 状态 | 将执行态变成可观察态 |
| Frontend App | `apps/tracking-viewer/` | React + Vite viewer，展示目标框、记忆、会话历史、状态标签 | 项目演示和操作反馈界面 |
| Runtime Scripts | `scripts/` | 启 perception、tracking loop、viewer stream、frontend、stack | 负责部署与进程编排，而不是内核逻辑 |

## 6. Embodied Agent Loop：Perception -> Planning -> Action

这个仓库里的 embodied loop 不是经典机器人里那种“一个无限 while 循环包办所有事情”，而是分成持续感知和事件驱动 turn 两条链。

### 6.1 持续感知链

- `run_tracking_perception.py` 从 camera 或视频源采样。
- 使用 Ultralytics tracking 推出当前 frame 与 candidate detections。
- `LocalPerceptionService` 维护最近 observation window，并把结果写到 `perception/.../snapshot.json`。
- 同时保存关键帧路径，供后续 tracking memory / viewer 使用。

### 6.2 单轮决策链

一次 turn 的标准处理路径是：

1. 文本输入进入 `backend/cli.py`。
2. `PiAgentRunner` 从 `session.json` 读取会话状态，并拿到当前 perception snapshot。
3. runner 生成：
   - `route_context.json`
   - 每个 skill 的 `skill_context.json`
   - `turn_context.json`
4. 如果是显式的 deterministic direct path，直接走 skill 的本地入口。
5. 否则 runner 调用 Pi，让它只在当前已启用的 skills 中做路由和推理。
6. skill 返回统一 JSON payload。
7. runner 把 `session_result`、`skill_state_patch`、`perception_cache_patch` 等应用到持久化 session。
8. 如有需要，再异步触发 rewrite worker 等慢操作。

### 6.3 Action 的含义

在当前仓库里，`action` 不是大而全的机器人运动控制栈，而是 capability 结果：

- 对 tracking：`track` / `wait` / `ask` / grounded reply
- 对 speech：生成语音文件或 TTS 输出
- 对 viewer：更新展示态

也就是说，这个仓库当前更像 **embodied decision kernel**，而不是一个完整 motion stack。

## 7. Runtime / Backend / App / Skill / Data Flow 关系

### 7.1 Runtime 关系

README 推荐的 tracking 运行形态是 3 个长期进程 + 1 个可选前端：

```text
Perception Process
    continuous sensing and snapshot writing

Tracking Loop
    polls session + perception and triggers continuation turns

Viewer Stream
    publishes fused agent/perception/module state over websocket

Frontend (optional)
    renders tracking-viewer UI
```

这里的关键点是：**tracking loop 是 skill-oriented runtime helper，不是系统总控中心**。系统真正的核心仍然是统一 runner 和统一 session state。

### 7.2 Data Flow 关系

| 数据对象 | 典型位置 | 作用 | 谁写入 | 谁消费 |
| --- | --- | --- | --- | --- |
| Active Session | `active_session.json` | 标记当前活跃会话 | perception / start 命令 | runner、viewer、CLI |
| Session Truth | `sessions/<id>/session.json` | agent 会话主状态，包括 latest_result、history、skill_cache | runner / store | viewer、loop、CLI |
| Perception Snapshot | `perception/sessions/<id>/snapshot.json` | 最新 observation、recent window、stream status | perception service | runner、viewer、tracking skill |
| Keyframes / Crops | `perception/keyframes/`、artifacts 目录 | 目标确认、memory rewrite、viewer 图像展示 | perception / tracking skill | tracking skill、viewer |
| Turn Artifacts | `.runtime/pi-agent/requests/...` | route context、skill context、prompt、调试输出 | runner | Pi / 调试者 |

### 7.3 App 与 Backend 的关系

前端 `tracking-viewer` 并不直接驱动业务逻辑。它订阅 viewer websocket，展示：

- 当前 session 是否可用
- 最新 frame 与 detection overlay
- 当前绑定的 target
- tracking memory
- conversation history / latest result

这意味着前端只是一个 read-only projection layer，降低了 UI 对内核的侵入性。

## 8. Skill 插拔模型

这个仓库最值得汇报的一点，是它已经把 skill 接入边界收敛到了统一 surface。

当前 backend 聚合的典型 hook 包括：

- `build_route_summary`
- `build_turn_context`
- `should_direct_init`
- `process_direct_init`
- `process_direct_turn`
- `schedule_rewrite`
- `build_viewer_module`

其含义不是“所有 skill 都必须很复杂”，而是 backend 只认统一协作点：

- skill 可以提供自己的 route summary
- skill 可以提供自己的 specialized context
- skill 可以声明某些 turn 走 deterministic 直通路径
- skill 可以提供 viewer 模块
- skill 可以把慢操作放到 rewrite / worker 上，而不是阻塞主 turn

`tracking` skill 是最完整的样例；`speech` 与 `web_search` 则证明 backend 主干不需要为新增 skill 写专属逻辑。

## 9. 关键设计理由与 Tradeoffs

### 9.1 Chat-first vs Perception-first

**选择**：turn 由聊天或事件触发，perception 只提供上下文。  
**好处**：系统更像 agent，而不是 tracker 外挂对话框。  
**代价**：如果未来要做高频闭环控制，需要额外设计更严格的实时控制平面。

### 9.2 Single Session Truth vs 多份 memory

**选择**：`session.json` 是 agent-owned state 主真相源。  
**好处**：调试、回放、viewer 聚合和 skill patching 都有统一落点。  
**代价**：当前更适合单机会话与文件级共享，不是天然的分布式架构。

### 9.3 File-backed Shared State vs Event Bus

**选择**：perception、runner、viewer、loop 都通过本地共享状态文件协作。  
**好处**：依赖极少、易部署、问题定位直观。  
**代价**：跨机器扩展、并发协调、强一致性与高吞吐不是现阶段重点。

### 9.4 Direct Skill Path vs Fully LLM-mediated Routing

**选择**：tracking 的 `init` / `track` 支持 deterministic direct path。  
**好处**：脆弱流程不完全依赖 LLM，关键动作更稳。  
**代价**：需要 skill 自己维护更强的入口脚本和结果契约。

### 9.5 Async Rewrite vs Inline Completion

**选择**：tracking memory rewrite 脱离主 turn，在后台 worker 处理。  
**好处**：降低主交互延迟，保持用户反馈及时。  
**代价**：最终 memory 更新是 eventual consistency，而不是同步完成。

### 9.6 Generic Viewer Shell vs Tracking-only UI

**选择**：backend 提供统一 viewer shell，skill 注入 module payload。  
**好处**：viewer 可以继续扩展到其他 skill。  
**代价**：viewer 的公共 schema 需要持续保持克制，避免重新长成大框架。

## 10. 部署视图

### 10.1 当前推荐部署模式

对 tracking 演示来说，推荐部署形态是：

- 一个 perception 进程，持续写 observation
- 一个 tracking loop，按状态推进 continuation turn
- 一个 viewer stream 进程，对外发布 websocket
- 一个可选 React frontend，做现场展示

这几个进程共享：

- 同一个 `state-root`
- 同一个 `session_id`
- 同一套 artifacts 目录

### 10.2 为什么这种部署是合理的

- 进程职责清晰，便于单独重启与定位问题
- viewer 可选，不会卡住主流程
- perception 与 agent 决策解耦，便于后续替换感知源
- 仍然保持单机可运行，不引入额外服务依赖

## 11. 可扩展性判断

从当前仓库实态看，这个项目已经具备“继续长能力而不是继续长框架”的基础。

### 已经具备的扩展点

- 新增 skill 可以直接放在 `skills/<name>/`
- runner 会基于已启用 skill 自动构建 route summary 与 turn context
- viewer 可通过 `build_viewer_module` 扩展
- 脚本层可以按 capability 增加 loop / helper，而不改变内核主链

### 当前不应过早抽象的部分

- 不必急着引入通用消息总线
- 不必急着引入复杂 plugin lifecycle framework
- 不必为了多 skill 再拆一层更泛化的 runtime wrapper

项目的方向很明确：先把内核保持小而硬，再按能力增长。

## 12. 风险、边界与未来工作

### 当前边界

- 当前最成熟的 embodied capability 仍然是 tracking。
- 系统主要围绕单机、本地共享状态、单活跃 session 模式组织。
- perception 当前聚焦视觉 tracking 场景，不是通用多传感器融合平台。
- action 面仍以 capability 结果和轻量执行接口为主，还不是完整机器人控制栈。

### Future Work

- **更强的部署韧性**：为 perception、loop、viewer 增加更清晰的健康检查与恢复策略。
- **更通用的 capability 接口**：在保持 skill surface 克制的前提下，接入更多 embodied 能力。
- **更强的 observability**：补齐 turn latency、skill routing、rewrite worker 等指标。
- **多设备 / 远程部署能力**：如果未来跨机器部署成为刚需，再考虑从文件共享迁移到更明确的 service / bus 架构。
- **更完整的 action plane**：把当前“结果型 action”逐步扩展到更真实的机器人执行闭环。

## 13. 汇报结论

`tracking_agent` 当前最值得强调的，不是某一个 tracking 算法细节，而是它已经把 embodied agent 方案收敛成一个清晰、可解释、可扩展的技术骨架：

- 持续感知只做感知
- 单轮 runner 只做决策编排
- session state 只有一个真相源
- skill 通过统一 surface 接入
- viewer 只是展示层

这使得项目从“为 tracking 服务的一组脚本”进化为“以 tracking 为样板能力的 embodied agent kernel”，也为后续接入更多能力留下了足够清晰的演进路径。
