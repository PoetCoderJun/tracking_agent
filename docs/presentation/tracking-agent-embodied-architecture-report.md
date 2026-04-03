# Tracking Agent：从“看见人”到“会跟着人走”的 Embodied Agent 方案

副标题：一份真正给人讲的项目说明，而不是给代码审计看的流水账  
版本：storytelling / human-readable edition  
日期：2026-04-02

---

## 0. 先讲一句人话：这个项目到底在做什么？

如果只用一句话介绍 `tracking_agent`，我会这样讲：

> 它不是一个“会框人”的 tracking demo，
> 而是一套让机器人 **持续看世界、按对话理解任务、在状态里记住对象、再把结果稳定执行出来** 的 embodied agent 技术骨架。

也就是说，它想解决的不是“目标检测准不准”这一个点，而是下面这个完整链条：

- 机器人能不能一直看着现实世界？
- 用户能不能用自然语言告诉它“去跟着那个人”？
- 系统能不能把“那个人是谁”记住，而不是每一轮都重新猜？
- 当目标短暂丢失、重新出现、或者用户要求切换时，系统能不能继续工作？
- 前端能不能把这一切清楚地展示出来，而不是黑盒运行？

这就是 embodied agent 真正难的地方：
**不是某个模块强，而是整条链必须连起来。**

---

## 1. 为什么普通 tracking demo 不够？

很多 tracking demo 的问题，不在于它不能跑，而在于它只能在“算法演示”那一刻跑得漂亮。

常见 demo 的典型形态是：

1. 摄像头进来
2. 模型框人
3. 输出一个 track id
4. 在屏幕上画框

这当然有用，但它离“机器人助手”还差很远。

因为一个真正可用的 embodied agent，面对的不是单帧画面，而是一个连续的、会变化的现实场景。它必须回答这些问题：

- 用户说的“那个穿黑衣服的人”，到底对应哪一个目标？
- 下一秒画面变了，它怎么知道还是同一个人？
- 如果画面里一下出现三个人，它是继续跟原来的，还是要问一句？
- 如果 tracking 暂时不稳，它是应该继续尝试、等待、还是向用户澄清？
- 如果前端想显示当前状态，应该从哪里读“系统当前到底认为自己在做什么”？

所以，这个项目的核心设计不是“把 tracking 接到 chat 上”，而是：

> **把 perception、对话理解、状态持久化、技能调用和展示层，收敛成同一个 agent runtime。**

这也是这个仓库最值得讲的地方。

---

## 2. 这套方案的核心思想：不要让任何一个模块变成“整个系统”

这个仓库的设计很克制，它没有试图造一个无所不能的大框架，而是坚持了几个非常重要的边界。

### 2.1 perception 只负责“看见”

感知层长期运行，持续把最新观察写出来。

它负责的事情包括：
- 读 camera / video
- 产出 detections / tracking 结果
- 形成 observation window
- 保存 keyframes / snapshot

但它**不负责高层决策**。

换句话说，perception 负责告诉系统：
> “世界现在长什么样。”

而不是替系统决定：
> “下一步该怎么做。”

### 2.2 runner 只负责“处理这一轮”

整个系统有一个非常清晰的单轮主链：

- 收到一次用户输入，或 loop 触发一次 continuation
- 读取当前 session 状态
- 读取 perception snapshot
- 构造 route context
- 判断该走哪个 skill / 哪条路径
- 返回结构化结果并落盘

也就是说，runner 的职责不是“永远运行”，而是：

> **每来一个 turn，就认真处理完这一个 turn。**

这让系统的状态边界变得很清楚，不会糊成一个巨大 while loop。

### 2.3 session state 只有一个主真相源

这套设计里，一个非常关键的决定是：

> `session.json` 是 agent-owned state 的主真相源。

这意味着：
- 当前对话到哪一步了
- 当前正在跟谁
- 上一轮结果是什么
- skill cache 里记住了什么

这些都统一落在一个 session 状态里，而不是分散在多个 memory 文件、多个缓存、多个前端状态里互相猜。

这是系统可解释性的基础。

### 2.4 skill 是能力模块，不是系统分叉

tracking、speech、web_search 都以 skill 的方式接入。

它们的意义不是“多几个功能”，而是证明这套 runtime 的主干已经抽象到位：

- 新能力可以接进来
- 但 backend 主干不用因为新 skill 而变形
- viewer 也可以按模块追加展示

这背后的设计哲学其实很重要：

> **继续长能力，不要继续长框架。**

### 2.5 viewer 只负责“把系统想法显示出来”

viewer 在这个项目里很重要，但它不是控制中心。

它做的是：
- 把 perception snapshot 读出来
- 把 session 状态读出来
- 把 skill viewer module 聚合起来
- 用 websocket 推给前端

所以 viewer 是一个 **read-only projection layer**。

它让人看懂系统，而不是替系统做决定。

---

## 3. 用一个故事讲完整套架构

假设现在有一个真实场景：

> 用户看着监控画面，对机器人说：
> **“开始跟踪最开始出现的穿黑衣服的人。”**

系统内部到底发生了什么？

### 第一步：系统先“看到世界”

perception 进程一直在跑。

它不断从视频流里读取画面，做 detection / tracking，然后把结果写成最新 snapshot。

这一层不需要等用户开口。它像机器人的“眼睛”，一直开着。

---

### 第二步：用户发出一个自然语言任务

用户并没有说“跟踪 ID 7”。
用户说的是：

> “最开始出现的穿黑衣服的人。”

这是一种带语义、带上下文、带歧义空间的指令。

这时系统不会直接冲去执行低层 tracking，而是先进入单轮 runner。

runner 会拿三类东西拼成这次 turn 的上下文：

- **对话上下文**：最近说了什么
- **世界上下文**：当前 perception 看到了什么
- **会话状态**：之前已经绑定了谁、上一轮发生了什么

这一步的意义很大：

> 系统不是在“听一句命令”，
> 而是在“结合当前世界和历史状态，理解这句话是什么意思”。

---

### 第三步：系统决定该走哪条处理路径

如果这是一个 tracking 的初始化请求，系统会进入 tracking skill。

但这里有个很聪明的设计：

对于像 `init`、`track` 这种脆弱、容易跑偏的流程，它不会完全交给开放式 LLM 推理，而是优先走 **deterministic entry script**。

为什么？

因为“跟踪谁”这种事，一旦走散了，用户体验会很差。

所以仓库做了一个很工程上成熟的选择：

- **开放式推理** 负责判断“这轮意图属于什么 skill / 什么 turn type”
- **确定性脚本** 负责执行 fragile workflow

这其实就是在说：

> 该让模型自由发挥的地方，让它发挥；
> 该收紧的地方，就别装浪漫。

---

### 第四步：系统把“那个人”正式绑定到 session 里

一旦目标确认成功，结果不会只存在某个函数返回值里。

它会被写进 session state：
- 当前 target_id 是谁
- 最近一次确认帧是什么
- latest_result 是什么
- tracking skill cache 记住了什么

这一步的重要性在于：

> 系统从“我这轮猜到是谁了”，
> 升级成“我现在正式知道自己正在跟谁”。

这就是 embodied agent 和一次性算法调用的区别。

它不是每一轮重新开始，而是进入一个持续状态。

---

### 第五步：tracking loop 接管“继续跟踪”

目标一旦被绑定，后面的任务就不再是“理解用户指令”，而是“在不断变化的世界里保持追踪”。

于是 tracking loop 开始周期性工作：

- 看看当前 target 还在不在
- 如果还在，就继续保持状态
- 如果不在，决定是等待、恢复、还是触发一次 continuation turn
- 必要时再把最新信息送回 runner

这里最妙的一点是：

> tracking loop 不是系统总控中心，它只是一个 **skill-oriented trigger**。

它的存在不是为了替代 runner，
而是为了在 tracking 这个具体能力上提供“持续推进”的动力。

这让系统避免了一个常见坏味道：
把所有长期逻辑、感知逻辑、决策逻辑、展示逻辑都塞进同一个大 loop 里。

---

### 第六步：viewer 把系统“脑子里的想法”展示出来

这时候 viewer 才出场。

viewer 读取：
- 当前 session 状态
- perception snapshot
- skill 提供的 viewer module

然后把这些聚合成一个前端能直接展示的状态流。

于是用户能看到：
- 最新画面
- 当前检测框
- 当前绑定的 target
- tracking memory
- 最近对话 / 当前状态

所以 viewer 的价值并不是“让 demo 更炫”，而是：

> 让这个 embodied agent 变得可观察、可解释、可调试。

---

## 4. 如果把整套系统压缩成一张图，它长这样

```text
现实世界（camera / video）
        ↓
[ Perception Service ]
持续读取画面，产出 detection / tracking / snapshot
        ↓
[ Persisted World State ]
perception snapshot、keyframes、recent frames
        ↓
用户 / loop / script 触发一次 turn
        ↓
[ PiAgentRunner ]
读取 session + perception，构造 route context
        ↓
判断该走哪个 skill / direct path / Pi path
        ↓
[ Skill Execution ]
tracking / speech / web_search ...
        ↓
[ Session Truth ]
session.json 写入 latest_result / skill_cache / conversation history
        ↓
[ Viewer Stream ]
把 agent state + world state 投影给前端
        ↓
[ Human-readable UI ]
让人看懂机器人现在“看到什么、记得什么、正在做什么”
```

这张图背后的重点不是“模块很多”，而是：

- 世界状态和会话状态被分清了
- 一次 turn 的处理链被分清了
- 能力扩展和内核主干被分清了
- 展示层和执行层被分清了

这就是它比 demo 更像系统的原因。

---

## 5. 这套架构最聪明的地方，不在“复杂”，而在“克制”

很多项目做到后面都会有一个诱惑：
既然我已经有 perception、loop、viewer、skill，那不如再搞一个更大的 orchestration framework，把所有东西都统一掉。

这个仓库目前反而做了更好的选择：

### 5.1 不把 perception 变成大脑

perception 负责看，不负责想。

好处是：
- 感知可以长期跑
- 决策可以独立演进
- 后续替换感知源时不会重写整个 runtime

### 5.2 不把 tracking loop 变成总控中心

tracking loop 只是 tracking 能力的推进器。

好处是：
- loop 不会绑架整个系统形状
- 未来别的 skill 也可以有自己的 runtime helper
- 系统主逻辑仍然收敛在 runner

### 5.3 不把 viewer 变成业务逻辑入口

viewer 只做投影，不做决策。

好处是：
- 前端可以改
- 展示可以变
- UI 不会反向塑造 runtime

### 5.4 不让 LLM 包办脆弱流程

tracking 的 `init` / `track` 明确使用 deterministic entry script。

好处是：
- 降低关键流程跑偏风险
- 更容易测试
- 更容易解释错误原因

这就是一种成熟的 embodied agent 工程思路：

> **把模型放在最有价值的位置，而不是把模型塞到所有位置。**

---

## 6. 主要组件，换一种“角色表”的讲法

如果把这个项目当成一部戏来看，各个模块其实像一组分工很清楚的角色。

| 角色 | 代表路径 | 它在故事里扮演什么角色 |
| --- | --- | --- |
| 眼睛 | `backend/perception/` | 一直看世界，把最新观察写下来 |
| 大脑的单轮工作台 | `backend/agent/runner.py` | 每来一个事件，就处理完这一轮 |
| 决策边界 | `backend/agent/pi_protocol.py` | 规定 Pi 能看到什么、该返回什么 |
| 记忆本 | `backend/persistence/` + `session.json` | 把“我现在在做什么”稳定记住 |
| 技能面板 | `backend/skills.py` | 让 tracking / speech / web_search 能接进同一系统 |
| 主力能力 | `skills/tracking/` | 负责目标初始化、继续跟踪、记忆更新 |
| 展示层 | `backend/agent_viewer_stream.py` + `apps/tracking-viewer/` | 把系统状态翻译成人能看懂的 UI |
| 舞台监督 | `scripts/` | 把 perception、loop、viewer、frontend 各自启动起来 |

这种设计的价值在于：

> 你能一眼看出谁在负责什么。

而一套系统一旦做到“谁负责什么”很清楚，它就更容易维护，也更容易扩展。

---

## 7. 部署形态也很像人能理解的系统，而不是魔法

当前推荐运行方式是：

- **1 个 perception 进程**：持续看世界
- **1 个 tracking loop 进程**：在 tracking 场景下推进持续行为
- **1 个 viewer stream 进程**：把状态流推给前端
- **1 个可选 frontend**：让人看见系统在想什么

这个部署方式好在哪里？

### 好处 1：出了问题容易定位

如果是 perception 崩了，你知道是“眼睛坏了”；
如果是 viewer 出问题，你知道是“展示层坏了”；
如果是 runner 出问题，你知道是“单轮决策主链坏了”。

这比把一切塞进一个大进程要健康太多。

### 好处 2：前端不是强依赖

你可以 headless 跑，也可以带前端演示跑。

这意味着系统既能做研究开发，也能做项目展示。

### 好处 3：状态共享方式简单直接

现在主要通过共享状态文件协作。

这不一定是未来分布式系统的终点，但对当前阶段非常合理：
- 简单
- 透明
- 好调试
- 不会过早工程化

---

## 8. 这套方案的 tradeoff 也要诚实地讲

真正像人的汇报，不是只说优点，也要说明它的边界。

### tradeoff 1：它更像 embodied decision kernel，还不是完整机器人控制栈

现在它已经能做：
- 看
- 记
- 理解用户意图
- 执行 grounded capability

但它还不是完整 motion stack。也就是说，
它更强在“决策与状态组织”，
而不是底层机器人运动控制闭环。

### tradeoff 2：它非常适合单机 / 单 session 形态，但还不是分布式多机架构

当前基于本地状态文件的协作方式，
对 robot / Pi 侧部署非常实用，
但如果未来上升到多设备、多节点协同，就需要更明确的 service / bus 设计。

### tradeoff 3：tracking 是当前最成熟的 embodied capability

这套系统已经证明可以接 skill，
但真正围绕 embodied 主场景打磨成熟的，仍然是 tracking。

这不是缺点，反而是好事：
说明它先把一个核心能力做扎实，而不是空泛地说“未来什么都能接”。

---

## 9. future work：下一步最值得做什么？

如果要继续把这个项目往前推，我认为最值得做的不是“再堆几个 feature”，而是沿着下面四条线继续长。

### 9.1 更强的部署韧性

把 perception、loop、viewer 的健康检查、超时恢复、异常重启补齐。

这会让它从“能跑的研究原型”更进一步变成“能持续运行的系统”。

### 9.2 更丰富的 embodied capabilities

在 tracking 之外，继续接入更多 grounded skill：
- spatial question answering
- action recommendation
- multimodal memory update
- environment-aware interaction

前提不是扩框架，而是沿着现在这条 skill surface 往里接。

### 9.3 更强的可观测性

如果要让系统真正工程化，就应该更系统地记录：
- turn latency
- route decision
- skill hit rate
- rewrite success / failure
- tracking recovery 质量

让系统不只是“跑起来”，而是“看得懂为什么这么跑”。

### 9.4 远程 / 多设备部署能力

如果未来要把 perception、agent、viewer 拆到不同机器上，
那时再引入更明确的 service 边界，会非常自然。

因为现在这套内核边界已经足够干净了。

---

## 10. 最后怎么讲，才像一个真正的人类 presentation？

如果你要拿这个项目去讲，我建议核心叙事不要从模型细节开始，而要从这句开始：

> **我们做的不是一个 tracking demo，**
> **而是一套让机器人能把“看见世界”和“理解任务”接起来的 embodied agent runtime。**

然后顺着这个逻辑讲：

1. **问题**：普通 tracking demo 只能框人，不能形成持续任务闭环  
2. **目标**：把 perception、对话理解、状态记忆和能力执行连成一条链  
3. **架构**：perception 常驻，runner 单轮处理，session 单源，skills 插拔，viewer 只读  
4. **效果**：系统知道自己正在跟谁、为什么这样做、以及怎么把状态展示给人  
5. **价值**：这是一套可继续扩能力的 embodied agent kernel，而不是一次性脚本堆叠  

---

## 11. 一段可以直接拿去讲的结尾

> `tracking_agent` 最值得强调的，不是它能把一个人框出来，
> 而是它已经把 embodied agent 最难的那条链条接通了：
> 
> - 机器人持续看世界
> - 用户用自然语言给任务
> - 系统在 session 里记住“我正在跟谁”
> - tracking loop 在现实变化中继续推进
> - viewer 把整个状态清楚地展示给人
> 
> 这让它从一个 tracking 功能，变成了一套真正可以继续长出更多能力的 agent runtime。

---

## 12. 最后压缩成五个关键词

- **持续感知**
- **单轮决策主链**
- **单一状态真相源**
- **能力可插拔**
- **系统可观察**

这五个词，基本就是这套 embodied agent 技术方案的骨架。