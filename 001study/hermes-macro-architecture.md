# Hermes Agent 源码宏观架构

*Hermes Read 第 0 课 — 宏观架构总览*
*—— 从 Python 视角理解一个 AI Agent 的核心骨架*

---

## 一、总览：Hermes 是什么？

**一句话：Hermes 是一个「核心引擎 + 多前端」的 AI Agent 系统。**

```
CLI 终端      Gateway 网关       TUI 界面      桌面应用
  (cli.py)    (gateway/)       (ui-tui/)      (Electron)
      │            │              │               │
      └────────────┴──────────────┴───────────────┘
                            │
                     ┌──────┴──────┐
                     │  AIAgent    │  ← run_agent.py 第 399 行
                     │  (核心引擎)  │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         ┌────┴───┐   ┌────┴───┐   ┌────┴───┐
         │ LLM    │   │ Tool   │   │ State  │
         │ 适配器  │   │ 执行器  │   │ 持久化  │
         └────────┘   └────────┘   └────────┘
```

核心文件：

| 文件 | 行数 | 职责 |
|------|:----:|------|
| `run_agent.py` | 6,629 | AIAgent 类，一切从这里开始 |
| `agent/conversation_loop.py` | 5,780 | Agent 主循环，消息→LLM→工具的闭环 |
| `agent/prompt_builder.py` | 2,066 | System Prompt 拼装 |
| `agent/tool_executor.py` | 1,801 | 工具调用调度 |
| `hermes_state.py` | 7,781 | 状态持久化 |
| `cli.py` | 15,903 | CLI chat 功能 入口（兼做很多事情） |

---

## 二、六层架构

### 第 1 层：前端层（Frontend）

**职责：** 接收用户输入，展示 Agent 响应。

**文件：**

- `cli.py` — Cli Chat模块（`kimi -p "..."` 或交互式 REPL）
- `gateway/run.py` — 多平台消息网关（Telegram / Discord / 飞书等 20+ 平台）
- `tui_gateway/` — TUI 界面后端
- `hermes_cli/` — CLI 子命令（安装、配置、模型切换等）

**与第 2 层的交互：**

```
CLI:  cli.py
    ↓ 创建 AIAgent 实例
    ↓ 调用 run_conversation(agent, user_message, ...)
    ↓ 阻塞等待返回
    ↓ 拿到结果字典，打印给用户

Gateway: gateway/run.py
    ↓ 收到平台消息
    ↓ 创建 AIAgent 实例
    ↓ 调用 run_conversation(...)
    ↓ 异步返回，结果通过回调发给平台 API
```

前端层做的事情不多——创建 `AIAgent`、调 `run_conversation()`、展示结果。所有"智能"都在下层。

---

### 第 2 层：Agent 引擎层（AIAgent）

**文件：** `run_agent.py:AIAgent`（第 399 行起）

**AIAgent 是一个 6,629 行的大类。** 它不是一个严格 OOP 意义上的"引擎"，更像一个**巨大的状态容器 + 工具袋**——把 LLM 调用、工具执行、错误处理、重试、Streaming 全部装在一个类里。

**核心构造函数参数（第 422-495 行）：**

```python
class AIAgent:
    def __init__(
        self,
        base_url=None,       # LLM API 地址
        api_key=None,        # API 密钥
        provider=None,       # 提供商名称（anthropic / openai / ...）
        api_mode=None,       # API 模式（anthropic_messages / chat_completions）
        model="",            # 模型名
        max_iterations=90,   # 每轮对话最大 tool call 次数
        tool_delay=1.0,      # tool 调用间隔
        # ... 还有 50+ 个参数 ...
        # 以及十几个回调函数：
        stream_delta_callback=None,   # 流式输出每个 token
        tool_progress_callback=None,  # 工具执行进度
        clarify_callback=None,        # 向用户提问
        event_callback=None,          # 通用事件
    )
```

**关键属性：**

- `agent.tools` — 当前启用的工具列表（LLM 能看到的 schema）
- `agent.api_mode` — 当前 LLM 适配模式
- `agent.session_id` — 当前会话 ID
- `agent.messages` — 当前对话历史
- `agent.provider` / `agent.model` / `agent.base_url` — 当前 LLM 配置

**关键方法（分散在 run_agent.py 中）：**

| 方法 | 行号 | 作用 |
|------|:----:|------|
| `_build_api_kwargs(api_messages)` | 5795 | 构建发送给 LLM 的请求参数 |
| `_interruptible_api_call(api_kwargs)` | 4841 | 发起 LLM 调用（可中断） |
| `_create_request_openai_client(...)` | 4252 | 创建 OpenAI 兼容客户端请求 |
| `_create_request_anthropic_client(...)` | 4316 | 创建 Anthropic 客户端请求 |
| `_get_transport()` | — | 获取当前适配器实例 |

**AIAgent 不包含主循环。** 主循环在第 3 层的 `conversation_loop.py` 中。

---

### 第 3 层：Agent 主循环（Conversation Loop）

**文件：** `agent/conversation_loop.py`

**入口函数：** `run_conversation()`（第 588 行）

**这是整个 Agent 的心脏。** 6 层架构中唯一的"主动循环"，其他层都是被它调用的。

**参数签名：**

```python
def run_conversation(
    agent,                        # AIAgent 实例
    user_message,                 # 用户消息
    system_message=None,          # 可选的 system prompt
    conversation_history=None,    # 历史消息
    task_id=None,                 # 任务 ID
    stream_callback=None,         # 流式回调
    persist_user_message=None,    # 持久化用的用户消息
    persist_user_timestamp=None,  # 持久化时间戳
    moa_config=None,              # MoA 配置
) -> Dict:                        # 返回结果字典
```

**主循环伪代码：**

```python
def run_conversation(agent, user_message, ...):
    # ── Prologue：准备工作 ──
    build_turn_context(agent, user_message, ...)
    # 包括：system prompt 构建、上下文压缩检查、
    #       记忆检索、配置加载、工具定义注入

    # ── 主循环 ──
    while True:
        # 1. 构建 API 请求参数
        api_kwargs = agent._build_api_kwargs(api_messages)

        # 2. 调用 LLM（同步阻塞）
        response = agent._interruptible_api_call(api_kwargs)

        # 3. 解析 LLM 响应
        if response 中有 tool_calls:
            # 3a. 执行工具
            execute_tool_calls_concurrent(agent, response, messages)
            # 3b. 把工具结果追加到 messages
            # 3c. 继续循环（回到第 1 步）
            continue

        elif response 中有文本回复:
            # 4. LLM 直接回复了文本 → 对话结束
            break

        elif 出错:
            # 5. 重试或报错
            retry_or_fail()

    # ── Epilogue：收尾 ──
    turn_finalizer.finalize(agent, ...)
    return result_dict
```

**关键点：**
- **同步循环。** 在处理 Tool Call 期间，整个 Agent 是"卡住"的。没有异步事件循环，没有并发。
- **Tool Call 循环次数上限 `max_iterations=90`**（默认值，可在 AIAgent 构造时修改）。
- **不存在"微压缩"概念。** Kimi Code 里面的 `microCompaction.detect()` 是每次 step 之前检查是否需要压缩——Hermes 没有这个，它的上下文压缩是在 turn 开始时一次性做的。

---

### 第 4 层：上下文层（Context Building）

**文件：**
- `agent/turn_context.py` — `build_turn_context()`（第 268 行），每次 turn 前的准备工作
- `agent/prompt_builder.py` — `build_system_prompt()`，拼装 system prompt
- `agent/coding_context.py` — 编码上下文（项目文件、AGENTS.md 等）
- `agent/context_engine.py` — 上下文引擎接口（插件化）

**System Prompt 的拼装过程（prompt_builder.py）：**

```
base system prompt（灵魂设定）
    + tool definitions（所有可选工具的 JSON schema）
    + memory contexts（从记忆系统检索的条目）
    + skill contexts（已启用的技能）
    + coding context（当前项目的上下文文件，如 AGENTS.md）
    + 各种 injection（goal 提醒、continuation 提示等）
    = final system prompt（几千到几万个 token）
```

**执行时机：**

`build_turn_context()` 在每轮对话第一次 LLM 调用之前执行一次，做以下事情：

1. 检查是否需要上下文压缩（如果消息太长就压缩）
2. 构建或恢复 system prompt
3. 检索记忆（从外部记忆系统读取相关条目）
4. 预热 todo/nudge 状态
5. 执行 `pre_llm_call` 插件钩子

---

### 第 5 层：工具层（Tool Execution & Tool Registry）

**文件：**

- `agent/tool_executor.py` — 工具调用调度器
- `tools/` — 40+ 个工具实现文件（每个工具一个文件或一族）
- `tools/registry.py` — 工具注册中心

**工具执行流程（execute_tool_calls_concurrent）：**

```python
def execute_tool_calls_concurrent(agent, assistant_message, messages, ...):
    # 1. 解析 tool_calls：遍历 LLM 返回的每个 tool_call
    # 2. 对每个 tool_call：
    #      a. 检查工具名称是否有效
    #      b. 解析参数（JSON parse）
    #      c. 检查权限/护栏
    #      d. 调用具体的工具函数
    # 3. 收集所有工具结果
    # 4. 将结果格式化为 tool_result 消息
    # 5. 追加到 messages
```

**真正的执行在 `tools/` 目录下：**

```
tools/file_tools.py          → Read、Write、Patch、SearchFiles
tools/terminal_tool.py       → Bash 命令执行
tools/web_tools.py           → WebSearch、WebFetch
tools/code_execution_tool.py → Python 代码执行
tools/browser_tool.py        → 浏览器自动化
tools/delegate_tool.py       → 子代理分发
tools/memory_tool.py         → 记忆读写
tools/computer_use_tool.py   → 桌面控制
tools/cronjob_tools.py       → 定时任务管理
...（40+ 个工具文件）
```

**工具注册中心（tools/registry.py）：**

- 维护一个 `name -> tool_function` 的字典
- 工具定义（tool schema）从这里提取，注入到 system prompt
- 工具调用时从这里查找具体的实现函数

---

### 第 6 层：Provider 适配层（Transport）

**文件：** `agent/transports/`

**基类：** `ProviderTransport`（`agent/transports/base.py` 第 16 行）

```python
class ProviderTransport(ABC):
    """将 Hermes 内部消息格式转换为各 Provider 特有的格式。"""

    @abstractmethod
    def convert_messages(self, messages, **kwargs) -> Any:
        """Hermes 消息 → Provider 格式"""

    @abstractmethod
    def convert_tools(self, tools) -> Any:
        """Hermes 工具定义 → Provider 格式"""

    @abstractmethod
    def build_kwargs(self, messages, tools, **kwargs) -> dict:
        """构建 API 请求参数"""

    @abstractmethod
    def normalize_response(self, response, **kwargs) -> NormalizedResponse:
        """Provider 响应 → Hermes 内部格式"""

    def validate_response(self, response) -> bool:
        """验证响应是否合法"""

    def extract_cache_stats(self, response) -> Optional[Dict]:
        """提取 prompt caching 统计"""

    def map_finish_reason(self, raw_reason: str) -> str:
        """映射 finish reason"""
```

**具体实现：**

| 文件 | 适配目标 |
|------|---------|
| `transports/anthropic.py` | Anthropic Messages API（Claude） |
| `transports/chat_completions.py` | OpenAI 兼容 API（OpenAI / DeepSeek / Kimi / 等） |
| `transports/bedrock.py` | AWS Bedrock |
| `transports/codex.py` | Codex Responses API |
| `transports/codex_app_server.py` | Codex App Server |

**为何需要这一层？** 不同 LLM Provider 的消息格式不同（Anthropic 用 `{"role":"user","content":"..."}`，OpenAI 用 `{"role":"user","content":[{"type":"text","text":"..."}]}`，Bedrock 用 `{"role":"user","content":[{"text":"..."}]}`）。Transport 层负责格式转换，让上层的循环代码不需要知道底层 Provider 的细节。

---

### 第 7 层：状态持久化层（State）

**文件：** `hermes_state.py`（7,781 行）

这个文件不属于 `agent/` 目录，但它在架构中至关重要——它负责：

- 会话状态的读写（Session ID、消息历史、配置）
- 检查点管理（Checkpoint）
- WAL（Write-Ahead Log）故障恢复
- SQLite 数据库操作

**AIAgent 中的状态字段：** `agent.state`、`agent.session_id`、`agent.messages`

---

## 三、层间交互全景图

```
用户输入 "写一个 Hello World"
    │
    ▼
┌─ 第 1 层：前端 ────────────────────────────┐
│ cli.py / gateway/run.py                     │
│ 创建 AIAgent → 调用 run_conversation()      │
│ 阻塞等待返回结果                            │
└─────────────────────────────────────────────┘
    │
    ▼
┌─ 第 2 层：Agent 引擎 ──────────────────────┐
│ AIAgent 实例（run_agent.py）                │
│ 持有：tools / messages / config / session   │
│ 提供：_build_api_kwargs / _interruptible    │
│       _api_call / _get_transport            │
└─────────────────────────────────────────────┘
    │
    ▼
┌─ 第 3 层：主循环 ──────────────────────────┐
│ run_conversation()                          │
│     ↓                                       │
│ ① build_turn_context()  ← 第 4 层上下文     │
│ ② _build_api_kwargs()    ← 第 2 层引擎      │
│ ③ _interruptible_api_call()                 │
│      ↓                                      │
│      transport.convert_messages()  ← 第 6 层 │
│      transport.build_kwargs()               │
│      HTTP POST → LLM Provider               │
│      transport.normalize_response()         │
│      ↑                                      │
│ ④ 解析响应                                  │
│    ├─ tool_calls? → execute_tool_calls()    │
│    │                ← 第 5 层工具执行器      │
│    │                  └→ 调用 tools/ 下的实现 │
│    └─ 文本回复? → break                      │
│ ⑤ 回到 ① 或结束                            │
└─────────────────────────────────────────────┘
    │
    ▼
返回 { "content": "你好！这是你的 Hello World 代码...", "tool_calls": [...] }
```

---

## 四、关键的设计模式

### 1. 回调驱动的流式响应

AIAgent 不直接返回流式数据。它在构造函数中接受一系列回调：

```python
agent = AIAgent(
    stream_delta_callback=lambda text: print(text, end=""),
    tool_progress_callback=lambda msg: show_spinner(msg),
    clarify_callback=lambda q: ask_user(q),
)
```

`run_conversation()` 内部在流式接收 LLM 响应时，通过 `stream_delta_callback` 逐个 token 吐出。前端（CLI/Gateway）通过这个回调实时渲染。

### 2. "Agent" 就是一堆属性

与其他 Agent 框架不同，Hermes 的 AIAgent 不是一个严格的"引擎"，它更像一个**属性袋子**：

```python
agent.model          # 当前模型
agent.provider       # 当前提供商
agent.base_url       # API 地址
agent.api_key        # API 密钥
agent.tools          # 工具列表
agent.messages       # 对话历史
agent.api_mode       # API 模式
agent.session_id     # 会话 ID
agent.state          # 状态对象
```

`run_conversation()` 和 `tool_executor.py` 都直接读写这些属性，不需要通过方法间接访问。

### 3. Transport 适配器模式

每个 Provider 有自己的 Transport 实现，负责：

```
Hermes 内部格式 → Provider 格式 → HTTP → Provider 格式 → Hermes 内部格式
    (Dict)       convert_messages()   POST    normalize_response()   (Dict)
```

`agent.api_mode` 决定用哪个 Transport：
- `"anthropic_messages"` → `anthropic.py`
- `"chat_completions"` → `chat_completions.py`
- `"bedrock_converse"` → `bedrock.py`

### 4. 状态持久化通过回调实现

`hermes_state.py` 不直接耦合到 AIAgent。状态的读写通过 AIAgent 初始化时传入的 `session_db` 对象实现。

---

## 五、与 Kimi Code 的对照

| 维度 | Hermes (Python) | Kimi Code (TypeScript) |
|------|-----------------|----------------------|
| 主循环 | `run_conversation()` 同步函数 | `runStepLoop()` async |
| Agent 表示 | 属性袋子 `AIAgent` | `class Agent` 组合模式 |
| 工具执行 | `execute_tool_calls_concurrent()` | `runToolCallBatch()` |
| Provider 适配 | `ProviderTransport` ABC | `LLM` 接口 |
| 上下文压缩 | turn 开始时一次性 | 微压缩 + 完全压缩两阶段 |
| 事件驱动 | 构造函数回调 | 事件发射器 emitEvent |
| System Prompt | `build_system_prompt()` 拼装 | `this.agent.injection.inject()` |

---

## 六、阅读路线建议

```
第 0 课：宏观架构          ← 你现在在这里
第 1 课：Agent 主循环      → agent/conversation_loop.py  run_conversation()
第 2 课：System Prompt     → agent/prompt_builder.py + turn_context.py
第 3 课：工具执行           → agent/tool_executor.py + tools/ 目录
第 4 课：Transport 适配层   → agent/transports/base.py + 具体实现
第 5 课：上下文与记忆       → agent/coding_context.py + context_engine.py
第 6 课：Agent 启动与状态   → run_agent.py AIAgent.__init__ + hermes_state.py
第 7 课：执行路径追踪       → 实战：一条消息的完整旅程
```

---

*Hermes Read — 2026-07-29*
*源码：/root/projects/hermes-agent-plus*
