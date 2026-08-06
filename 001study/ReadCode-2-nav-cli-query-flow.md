# CLI 查询流程导航

> 场景：`python cli.py -q "你的问题"` 或 `python cli.py "你的问题"`
> 目标：理解从输入到输出的完整调用链

---

## 核心调用链（7 步）

```
main() 入口
   ↓
cli.run() 或 cli.agent.run_conversation()
   ↓
agent/engine
   ↓
LLM API 调用
   ↓
工具执行 (_execute_tool_calls)
   ↓
返回结果渲染
   ↓
输出到终端
```

---

## 详细跳转（带行号）

### Step 1: main() 入口

```
位置：cli.py:15384
```

参数解析后，分支：

```python
# cli.py:15674
if query or image:      # ← 单次查询模式入口
    cli.agent.run_conversation()
else:
    cli.run()           # ← 交互模式（12749）
```

---

### Step 2: 单次查询模式核心

```
位置：cli.py:15793
```

```python
result = cli.agent.run_conversation(
    user_message=effective_query,
    conversation_history=cli.conversation_history,
)
```

**这里离开 CLI 层，进入 Agent 核心引擎。**

---

### Step 2.5: Agent 懒初始化（关键！）

```
位置：cli.py:11630 (在 chat() 函数内)
```

```python
if not self._init_agent(
    model_override=turn_route["model"],
    runtime_override=turn_route["runtime"],
    request_overrides=turn_route.get("request_overrides"),
):
    return None
agent = self.agent
```

**调用链：**

```
cli.py:11630  self._init_agent()
      ↓
hermes_cli/cli_agent_setup_mixin.py:226  def _init_agent()
      ↓
hermes_cli/cli_agent_setup_mixin.py:353  self.agent = AIAgent(...)
```

**关键点：**
- Agent 是**懒加载**的，首次调用 chat() 时才初始化
- `HermesCLI` 类继承自 `CLIAgentSetupMixin`（cli.py:3703）
- `_init_agent` 方法定义在 `hermes_cli/cli_agent_setup_mixin.py`
- 实际 `AIAgent` 类来自 `run_agent.py`（cli.py:841 懒加载导入）

---

### Step 2.6: `_init_agent` 常规初始化流程

> 场景：首次运行 `hermes chat`，不用 `--resume`，不用 `--session`

```
入口：cli.py:11630 → chat() → _init_agent()
```

#### Step 2.6.1: 快速检查 (mixin:235-236)

```python
# hermes_cli/cli_agent_setup_mixin.py:235-236
if self.agent is not None:
    return True  # 已初始化过，直接返回
```

#### Step 2.6.2: 前置准备 (mixin:238-247)

```python
# hermes_cli/cli_agent_setup_mixin.py:238
_prepare_deferred_agent_startup()     # 延迟启动准备

# hermes_cli/cli_agent_setup_mixin.py:239
self._install_tool_callbacks()         # 安装工具回调

# hermes_cli/cli_agent_setup_mixin.py:240
self._ensure_tirith_security()        # 安全检查

# hermes_cli/cli_agent_setup_mixin.py:242
self._ensure_runtime_credentials()    # 确保凭证有效

# hermes_cli/cli_agent_setup_mixin.py:247
wait_for_mcp_discovery()              # 等待 MCP 工具发现
```

#### Step 2.6.3: Session DB 初始化 (mixin:250-255)

```python
# hermes_cli/cli_agent_setup_mixin.py:250-255
if self._session_db is None:
    from hermes_state import SessionDB
    self._session_db = SessionDB()   # 首次创建 SQLite 会话存储
```

#### Step 2.6.4: 恢复会话? (mixin:261-340)

```python
# hermes_cli/cli_agent_setup_mixin.py:261
if self._resumed and self._session_db and not self.conversation_history:
    # 只有用 --resume <session_id> 才会走这里
    # 从数据库加载历史消息...
```

**常规场景不走这里**（`self._resumed = False`）

#### Step 2.6.5: 构建 runtime 配置 (mixin:342-352)

```python
# hermes_cli/cli_agent_setup_mixin.py:342-352
runtime = runtime_override or {
    "api_key": self.api_key,
    "base_url": self.base_url,
    "provider": self.provider,
    "api_mode": self.api_mode,
    "command": self.acp_command,
    "args": list(self.acp_args or []),
    "credential_pool": getattr(self, "_credential_pool", None),
}
effective_model = model_override or self.model
```

#### Step 2.6.6: **实例化 AIAgent** (mixin:353-404) — 核心！

```python
# hermes_cli/cli_agent_setup_mixin.py:353-404
self.agent = AIAgent(
    model=effective_model,                    # 模型名称
    api_key=runtime.get("api_key"),           # API 密钥
    base_url=runtime.get("base_url"),         # 自定义端点
    provider=runtime.get("provider"),          # provider (anthropic/openai...)
    api_mode=runtime.get("api_mode"),         # API 模式
    acp_command=runtime.get("command"),       # ACP 命令
    acp_args=runtime.get("args"),             # ACP 参数
    credential_pool=runtime.get("credential_pool"),
    max_tokens=self.max_tokens,               # 最大 token
    max_iterations=self.max_turns,            # 最大轮次
    enabled_toolsets=self.enabled_toolsets,   # 启用的工具集
    disabled_toolsets=self.disabled_toolsets, # 禁用的工具集
    verbose_logging=self.verbose,              # 详细日志
    quiet_mode=not self.verbose,               # 静默模式
    tool_progress_mode=getattr(self, "tool_progress_mode", "all"),
    ephemeral_system_prompt=self.system_prompt,  # 系统提示词
    prefill_messages=self.prefill_messages,      # 预填充消息
    reasoning_config=self.reasoning_config,       # 推理配置
    service_tier=self.service_tier,               # 服务层级
    request_overrides=request_overrides,           # 请求覆盖
    providers_allowed=self._providers_only,       # 允许的 provider
    providers_ignored=self._providers_ignore,      # 忽略的 provider
    providers_order=self._providers_order,         # provider 顺序
    provider_sort=self._provider_sort,             # provider 排序
    session_id=self.session_id,                   # 会话 ID
    platform="cli",                               # 平台标识
    session_db=self._session_db,                  # SQLite 会话存储
    clarify_callback=self._clarify_callback,      # 澄清回调
    reasoning_callback=self._current_reasoning_callback(),
    fallback_model=self._fallback_model,          # 备用模型
    thinking_callback=self._on_thinking,          # 思考回调
    checkpoints_enabled=self.checkpoints_enabled, # 检查点启用
    checkpoint_max_snapshots=self.checkpoint_max_snapshots,
    tool_progress_callback=self._on_tool_progress,  # 工具进度回调
    tool_start_callback=self._on_tool_start,       # 工具开始回调
    tool_complete_callback=self._on_tool_complete, # 工具完成回调
    stream_delta_callback=self._stream_delta,      # 流式增量回调
    tool_gen_callback=self._on_tool_gen_start,    # 工具生成回调
    notice_callback=self._on_notice,              # 通知回调
    notice_clear_callback=self._on_notice_clear,  # 通知清除回调
    reaction_callback=self._on_reaction,          # 反应回调
)
```

这就是 **Agent 真正诞生的时刻** 🎉

---

## `_init_agent` 完整调用链

```
cli.py:11630         chat() 调用 _init_agent()
       │
       ▼
cli_agent_setup_mixin.py:226    def _init_agent(...)
       │
       ├─→ 235: if self.agent is not None: return True
       │
       ├─→ 238: _prepare_deferred_agent_startup()
       ├─→ 239: self._install_tool_callbacks()
       ├─→ 240: self._ensure_tirith_security()
       ├─→ 242: self._ensure_runtime_credentials()
       ├─→ 247: wait_for_mcp_discovery()
       │
       ├─→ 250: SessionDB() 初始化
       │
       ├─→ 261: [可选] 从 DB 恢复会话历史
       │
       ├─→ 342: 构建 runtime 配置
       │
       └─→ 353: self.agent = AIAgent(...)  ← 核心：Agent 实例化！
```

---

### Step 3: Agent 核心引擎

```
真身位置：agent/conversation_loop.py:588
```

```python
def run_conversation(user_message, conversation_history, ...):
```

这是真正的 AI 引擎，包含：
- 消息构建
- LLM API 调用
- 工具调用循环
- 响应处理

---

### Step 4: 工具执行

```
位置：agent/conversation_loop.py 内部
调用：_execute_tool_calls()
```

或者通过：

```
cli.py:847  get_tool_definitions(*args, **kwargs)  ← 包装器
           → 真身：tools/tool_definitions.py
```

---

### Step 5: 返回结果渲染

```
位置：cli.py:15810
```

```python
response = result.get("final_response", "")
print(response)
```

---

### Step 6: 推理标签清洗（输出前）

```
位置：cli.py:196
```

```python
def _strip_reasoning_tags(text: str) -> str:
```

删除 AI 的思考过程（如 `<think>`），只输出最终答案。

---

### Step 7: 打印到终端

```
位置：cli.py:2639
```

```python
def _cprint(text):
    # 打印到控制台
```

---

## 关键函数速查表

| 行号 | 函数名 | 作用 |
|------|--------|------|
| 15384 | `main()` | CLI 入口，参数解析 |
| 15674 | `if query or image:` | 单次/交互模式分叉 |
| 15793 | `cli.agent.run_conversation()` | 进入 Agent 核心 |
| 12749 | `cli.run()` | 交互模式主循环 |
| 243 | `handle_enter()` | 交互模式下按回车后逻辑 |
| 588 | `run_conversation()` | Agent 核心引擎（真身） |
| 196 | `_strip_reasoning_tags()` | 清洗推理标签 |
| 2639 | `_cprint()` | 打印输出 |

---

## 快速跳转指令

```bash
# 入口
sed -n '15384p' cli.py

# 单次查询入口
sed -n '15674p' cli.py

# Agent 调用点
sed -n '15793p' cli.py

# 交互主循环
sed -n '12749p' cli.py

# 按回车处理
sed -n '243p' cli.py
```

---

## 最小阅读路径（只要理解流程）

建议只读这 4 个位置：

1. **cli.py:15674** — 判断单次还是交互
2. **cli.py:15793** — 调用 Agent 核心
3. **agent/conversation_loop.py:588** — Agent 引擎（真身）
4. **cli.py:15810** — 输出结果

其余 15903 行，**遇到问题再查**。

---

## 交互模式完整路径（带队列设计）

交互模式稍微复杂，用了双队列设计：

```
用户输入
   ↓
handle_enter() (12991)     ← 按回车，收集输入
   ↓
_pending_input.put(payload) (13185)  ← 放入待处理队列
   ↓
process_loop() (14783)      ← 后台线程从队列取输入
   ↓
chat() (11590)             ← 每轮对话准备
   ↓
run_conversation()         ← Agent 核心
```

---

### 交互模式核心：双队列设计

```
┌─────────────────────────────────────────────┐
│  handle_enter()                            │
│    ├── sudo/secret/approval/clarify 状态    │
│    └── 普通输入 → _pending_input 队列       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  process_loop()  (后台线程)                │
│    └── 从 _pending_input 取输入            │
│        ├── 命令 (/xxx) → process_command() │
│        └── 普通消息 → chat()                │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  chat() (11590)                             │
│    ├── _ensure_runtime_credentials()       │
│    ├── _resolve_turn_agent_config()        │
│    ├── _init_agent()                      │
│    └── agent.run_conversation()            │
└─────────────────────────────────────────────┘
```

---

### 交互模式关键状态

| 状态变量 | 作用 |
|----------|------|
| `_pending_input` | 待处理输入队列（用户回车后放入） |
| `_interrupt_queue` | 中断队列（Agent 运行时输入放入这里） |
| `_agent_running` | Agent 是否正在运行 |
| `_should_exit` | 是否应该退出 |

---

### handle_enter() 核心逻辑 (12991)

```python
def handle_enter(event):
    # 1. Sudo 密码输入
    if self._sudo_state:
        self._sudo_state["response_queue"].put(text)
        return
    
    # 2. Secret 输入
    if self._secret_state:
        self._submit_secret_response(text)
        return
    
    # 3. Clarify 选择
    if self._clarify_state:
        # ...
        return
    
    # 4. 普通输入 → 根据 Agent 状态决定
    if self._agent_running:
        if busy_input_mode == "queue":
            _pending_input.put(payload)      # 排队
        elif busy_input_mode == "interrupt":
            _interrupt_queue.put(payload)    # 中断
    else:
        _pending_input.put(payload)          # 空闲状态直接排队
```

---

### process_loop() 核心逻辑 (14783)

```python
def process_loop():
    while not self._should_exit:
        # 从队列取输入
        user_input = self._pending_input.get(timeout=0.1)
        
        # 检查命令
        if _looks_like_slash_command(user_input):
            self.process_command(user_input)
            continue
        
        # 调用 chat
        self.chat(user_input, images=submit_images)
```

---

### chat() 核心逻辑 (11590)

```python
def chat(message, images=None):
    # 1. 确保凭证有效
    if not self._ensure_runtime_credentials():
        return None
    
    # 2. 决定这轮用哪个 agent 配置
    turn_route = self._resolve_turn_agent_config(message)
    
    # 3. 初始化 agent（懒加载）
    if self.agent is None:
        self._init_agent(...)
    
    # 4. 运行对话
    self.agent.run_conversation(
        user_message=message,
        conversation_history=self.conversation_history,
    )
```

---

## 相关阅读

- [ReadCode-3-代码阅读方法论](ReadCode-3-how-to-read-code.md) — 如何处理边缘分支、提升阅读效率

---

*2026-08-05*
