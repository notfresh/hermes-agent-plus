# Hermes Read 第 1 课 — Agent 主循环 (conversation_loop.py)

> 本文档对 `agent/conversation_loop.py` 中的 Agent 主循环进行结构化分析。这是 Hermes Agent 核心引擎的"心脏"——消息→LLM→工具的闭环。

---

## 一、文件定位

| 项目 | 值 |
|------|-----|
| **文件路径** | `agent/conversation_loop.py` |
| **总行数** | 5,780 行 |
| **核心函数** | `run_conversation()`（第 588 行 ~ 第 5776 行，约 5,188 行） |
| **文档字符串** | "Run a complete conversation with tool calling until completion." |

**说明：** 这是从 `run_agent.py` 的 `AIAgent` 类中提取出来的最大块。函数接收 `AIAgent` 实例作为第一个参数，通过属性读写来访问其状态——而不是通过方法调用。这种设计让主循环与引擎状态紧密耦合，但也使得代码集中、便于追踪。

---

## 二、函数签名

```python
def run_conversation(
    agent,                        # AIAgent 实例
    user_message,                 # 用户消息
    system_message=None,          # 可选的 system prompt（覆盖 ephemeral_system_prompt）
    conversation_history=None,    # 历史消息列表
    task_id=None,                 # 任务 ID
    stream_callback=None,         # 流式回调（每个文本 delta 调用一次）
    persist_user_message=None,    # 干净的用于持久化的用户消息
    persist_user_timestamp=None,  # 持久化时间戳
    moa_config=None,              # MoA 配置
) -> Dict:
```

**返回值 Dict 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `final_response` | str | 最终回复文本 |
| `messages` | list[dict] | 完整消息历史 |
| `completed` | bool | 是否完成 |
| `api_calls` | int | API 调用次数 |
| `error` | str\|None | 错误信息（如果有） |

---

## 三、主循环三阶段架构

`run_conversation()` 的执行逻辑可以清晰地划分为**三个阶段**：Prologue（准备）、Main Loop（核心循环）、Epilogue（收尾）。

### 第一阶段：Prologue（turn 准备）

**入口：** `build_turn_context()`（第 641 行）

这一阶段的目标是准备好 turn 所需的全部上下文。具体包括：

1. **stdio 防护** — 检查是否有终端运行，避免在无终端环境下执行交互式操作
2. **重试计数器重置** — 将 API 调用重试次数归零
3. **消息清洗** — 清理消息历史中的不合理条目（空消息、非法 role 等）
4. **System Prompt 构建/恢复** — 如果系统提示被压缩过，从持久化存储恢复；否则调用 `prompt_builder` 重新构建
5. **预压缩** — 如果上下文超过阈值，在 LLM 调用前进行一次性压缩
6. **pre_llm_call 插件钩子** — 执行已注册的插件回调，允许插件在 LLM 调用前修改上下文
7. **外部记忆预取** — 从记忆系统（Memory Manager）检索与当前查询相关的条目
8. **故障恢复持久化** — 将当前上下文写入 WAL（Write-Ahead Log），用于崩溃恢复

**返回值：** `_ctx` 对象，包含以下关键字段：
- `user_message` — 处理后的用户消息
- `messages` — 完整消息列表
- `active_system_prompt` — 当前活跃的 system prompt
- `turn_id` — 当前 turn 的唯一标识符
- `compression_state` — 压缩状态（是否已压缩、压缩前的 token 数等）

### 第二阶段：Main Loop（核心循环）

**循环条件**（第 715 行）：

```python
while (api_call_count < agent.max_iterations 
       and agent.iteration_budget.remaining > 0) \
       or agent._budget_grace_call:
```

每次迭代包含以下步骤：

#### 步骤 ①：中断检查（第 720 行）
检查 `agent._stop_requested` 标志位。如果外部请求了停止（用户取消、超时等），立即 break 出循环。

#### 步骤 ②：消耗 iteration budget（第 736 行）
从 `agent.iteration_budget` 中扣除一次迭代的预算。如果预算耗尽且没有 `grace_call`，循环终止。

#### 步骤 ③：发送 step_callback（第 743 行）
调用 `agent.step_callback()` 通知 gateway hooks 当前迭代编号。这个回调用于前端展示进度条或状态指示器。

#### 步骤 ④：构建 api_messages（第 800+ 行）
将所有消息（system prompt + 历史消息 + 最新用户消息）组装成 LLM 可以处理的格式。这一步会：
- 合并 system prompt 到消息列表开头
- 添加 MoA 配置中的额外消息（如果启用）
- 确保消息角色严格交替（user/assistant/user/assistant...）

#### 步骤 ⑤：消息预处理（第 1000-1100 行）
- **Prompt Caching** — 为支持 prompt caching 的 Provider（如 Anthropic）添加缓存标记
- **工具参数修复** — 修复 LLM 可能输出的非法工具参数（如空字符串、无效 JSON）
- **消息清洗** — 移除空消息、合并连续的相同角色消息
- **空白标准化** — 去除首尾空白、统一换行符
- **Token 估算** — 估算当前消息列表的总 token 数

#### 步骤 ⑥：上下文压缩检查（第 1128-1179 行）
如果估算的 token 数超过 `agent.max_context_tokens` 阈值，调用 `agent._compress_context()` 进行压缩。压缩策略：
- 丢弃早期的 assistant 消息（保留 system prompt 和 user 消息）
- 对历史消息进行摘要
- 标记压缩后的消息为"已压缩"

#### 步骤 ⑦：调用 LLM（第 1436-1466 行）
```python
response = agent._interruptible_api_call(api_kwargs)
```
内部流程：
1. `agent._get_transport().convert_messages(api_messages)` — 转换为 Provider 格式
2. `agent._get_transport().build_kwargs(messages, tools)` — 构建请求参数
3. `HTTP POST → LLM Provider` — 发送请求
4. `agent._get_transport().normalize_response(raw_response)` — 标准化响应

#### 步骤 ⑧：LLM 响应验证（第 1486-1565 行）
验证响应是否合法：
- 检查 HTTP 状态码
- 检查响应结构是否完整（有 `content` 字段）
- 检查 `finish_reason` 是否是已知值
- 检查 `content` 中的角色是否合规

#### 步骤 ⑨：无效响应处理（第 1590-1725 行）
如果响应无效，尝试重试或回退：
- **第一次失败** → 去除 tools 重试（可能是工具定义导致模型出错）
- **第二次失败** → 完全去掉 tools 重试（退化为纯对话模式）
- **第三次失败** → 返回错误结果给用户

#### 步骤 ⑩：提取 finish_reason（第 1728-1775 行）
从标准化响应中提取 `finish_reason`，并进行 Provider 特定的归一化映射。

#### 步骤 ⑪：根据 finish_reason 分流

| finish_reason | 处理路径 | 说明 |
|---------------|----------|------|
| `'tool_use'` | → 执行工具（第 4701-5055 行），然后 `continue` | 工具调用循环 |
| `'stop'` / `'end_turn'` | → 提取文本回复，`break` | 对话结束 |
| `'length'` | → 截断处理，重试 | 响应过长 |
| `'content_filter'` | → 内容策略拦截，返回错误 | 违反安全策略 |

#### 步骤 ⑫：记录用量与持久化（第 2200-2400 行）
每次 LLM 调用后记录：
- API 调用次数（`api_call_count += 1`）
- Token 用量（input_tokens, output_tokens）
- 耗时
- 持久化当前消息到 SQLite 数据库

### 第三阶段：Epilogue（收尾）

**流程：**
1. **turn_finalizer 处理** — 调用 `agent.turn_finalizer.finalize()` 执行 turn 级别的收尾工作
2. **记忆回顾** — 将本轮对话的关键信息写入记忆系统（memory_manager）
3. **Kanban 停止循环检查** — 如果配置了 Kanban 看板模式，检查是否需要停止循环
4. **构建返回结果字典** — 组装最终返回值 `{final_response, messages, completed, api_calls, error}`

---

## 四、Tool Call 处理的子流程

当 `finish_reason == 'tool_use'` 时，进入工具调用子流程。这是主循环中最复杂的分支。

### 子流程步骤

**① 打印日志（第 4703 行）**
```
🔧 Processing N tool call(s)...
```

**② 验证并修复工具名称（第 4713-4718 行）**
检查工具名称是否在注册表中存在。对于部分 Provider（如 Anthropic），工具名称可能包含命名空间前缀，需要剥离。

**③ 检测无效工具名称（第 4719-4737 行）**
如果工具名称不在注册表中：
- 检查是否为拼写错误或 LLM 幻觉生成的虚构工具
- 如果是虚构工具，返回"不存在的工具"错误给 LLM，让它重新生成

**④ 解析 JSON 参数（第 4824-4852 行）**
每个工具调用的参数是 JSON 字符串。解析过程中：
- 检测 JSON 截断（参数不完整）
- 修复常见的 JSON 语法错误（尾部逗号、缺失引号）

**⑤ JSON 无效时的重试逻辑（第 4854-4868 行）**
如果 JSON 解析失败：
- 首次失败：返回 JSON parse error 给 LLM，要求重新生成
- 再次失败：尝试用 ast.literal_eval 做 fallback 解析

**⑥ 持久化 assistant tool-call turn（第 5034 行）**
将 LLM 返回的 tool_call 消息写入持久化存储，确保崩溃后可恢复。

**⑦ 关闭流式显示（第 5049 行）**
如果正在流式输出文本，关闭流式标记，准备输出工具执行结果。

**⑧ `agent._execute_tool_calls()`（第 5055 行）—— 关键调用！**
这是实际的工具执行入口。内部流程：
1. 遍历所有 tool_call
2. 使用线程池并发执行独立工具（如果工具声明为无状态且可并发）
3. 串行执行有状态工具（如 computer_use）
4. 收集工具执行结果
5. 格式化结果并追加到 `messages`

**⑨ 检查 tool guardrail halt 决策（第 5057 行）**
某些工具执行后可能触发护栏检查（例如检测到危险操作）。如果护栏要求停止，设置标志位并准备退出。

**⑩ 预算退还（第 5096 行）**
如果执行的是 `execute_code` 工具，退还部分 iteration budget（因为代码执行不消耗 LLM API 次数）。

**⑪ 继续循环**
回到主循环的 ② 构建 api_messages，准备下一次 LLM 调用。

### 失败模式汇总

| 失败类型 | 处理策略 | 说明 |
|----------|----------|------|
| 工具名不存在 | 返回错误给 LLM | 让 LLM 重新生成 |
| JSON 参数无效 | 重试 1 次 + fallback | ast.literal_eval 兜底 |
| 工具执行超时 | 返回 timeout 错误 | 20 秒超时 |
| 工具执行异常 | 返回异常信息 | 精确的异常栈 |
| 护栏拦截 | 停止循环 | 安全优先 |

---

## 五、与 Kimi Code 对照

| 维度 | Hermes | Kimi Code |
|------|--------|-----------|
| **循环入口** | `run_conversation()` | `runStepLoop()` |
| **语言** | Python 同步 | TypeScript async |
| **Tool 循环上限** | `max_iterations=90` | `maxStepsPerTurn` |
| **压缩时机** | turn 开始时 + 每次 API 调用前检查 | 微压缩（每步）+ 完全压缩 |
| **并行执行** | 同步，单线程 | async 并发 |
| **Provider 适配** | Transport 基类 + 各 Provider 实现 | LLM 接口 |
| **事件系统** | 回调函数 | emitEvent RPC |
| **消息格式** | Hermes 内部 dict → Provider 格式 | 统一的 Message 类型 |
| **重试策略** | 降级退让（先去 tools → 再去 tools） | retryWithFallback |
| **记忆系统** | 独立的 Memory Manager | 内置在 StepLoop 中 |
| **中断机制** | `_stop_requested` 标志位 | AbortSignal |
| **流式输出** | 回调函数逐 token | AsyncGenerator |

---

## 六、关键流程图

```
run_conversation(agent, user_message, ...)
    │
    ├─ ═══════════════════════════════════════
    ├─ ① Prologue: build_turn_context()
    │     ├─ stdio 防护
    │     ├─ 重置重试计数器
    │     ├─ 消息清洗 & system prompt 构建
    │     ├─ 预压缩 & pre_llm_call 钩子
    │     ├─ 外部记忆预取
    │     └─ 故障恢复持久化 (WAL)
    │     ↓ 返回 _ctx
    │
    ├─ ═══════════════════════════════════════
    ├─ ② Main Loop (while api_calls < max_iterations)
    │     │
    │     ├─ 中断检查 (_stop_requested?)
    │     ├─ 消耗 iteration_budget
    │     ├─ step_callback (通知前端)
    │     ├─ 构建 api_messages
    │     ├─ 消息预处理 (caching, 工具参数修复, 清洗)
    │     ├─ 上下文压缩检查 (_compress_context?)
    │     ├─ _interruptible_api_call()
    │     │     ├─ transport.convert_messages()
    │     │     ├─ transport.build_kwargs()
    │     │     ├─ HTTP POST → LLM Provider
    │     │     └─ transport.normalize_response()
    │     │
    │     ├─ 响应验证 & finish_reason 提取
    │     │
    │     ├─ finish_reason 分流 ────────────────────┐
    │     │     │                                    │
    │     │     ├─ 'tool_use' ───┐                   │
    │     │     │   ├─ 验证工具名  │                   │
    │     │     │   ├─ 解析 JSON  │  ─── 工具执行 ────┤
    │     │     │   ├─ _execute_t│                    │
    │     │     │   ├─ 护栏检查   │                    │
    │     │     │   └─ continue ──┴───────────────────┤
    │     │     │                                     │
    │     │     ├─ 'stop'/'end_turn' ──┐              │
    │     │     │   ├─ 提取文本回复    │              │
    │     │     │   ├─ 记忆回顾       │              │
    │     │     │   ├─ Kanban 检查    │              │
    │     │     │   └─ break ────────┴──────────────┤
    │     │     │                                     │
    │     │     ├─ 'length' ──→ 截断重试             │
    │     │     └─ 'content_filter' ──→ 错误返回      │
    │     │                                          │
    │     └─ 记录用量 & 持久化 (SQLite) ────────────┘
    │
    ├─ ═══════════════════════════════════════
    ├─ ③ Epilogue: 收尾
    │     ├─ turn_finalizer.finalize()
    │     ├─ 记忆回顾 (memory_manager)
    │     ├─ Kanban 停止循环检查
    │     └─ 返回结果字典
    │
    └─ Return { final_response, messages, completed, api_calls, error }
```

---

## 七、关键设计洞察

### 1. 同步阻塞模型

Hermes 的主循环是**纯同步**的。从 `cli.py` 调用 `run_conversation()` 到最终返回，整个调用栈是同步阻塞的——没有协程、没有 `async/await`。这与 Kimi Code（TypeScript async/await）形成鲜明对比。

这意味着：
- **调试简单**：调用栈清晰，没有"回调地狱"或协程上下文切换
- **并发受限**：工具执行即使使用线程池，主线程仍被阻塞
- **状态管理直观**：没有必要为异步共享状态加锁

### 2. 回调驱动的输出

所有"推送"行为（流式文本、工具进度、用户提问）通过 AIAgent 构造时传入的回调函数实现：
- `stream_delta_callback(text)` — 流式输出的每个 token
- `tool_progress_callback(msg)` — 工具执行进度
- `clarify_callback(question)` — 需要向用户澄清

这种模式避免了主循环直接依赖前端实现，保持了循环的纯洁性。

### 3. 退化式重试策略

当 LLM 调用失败时，Hermes 采用**降级退让**策略：
1. 第一次失败 → 保持 tools，重试
2. 第二次失败 → 去除所有 tools，重试（降级为纯对话）
3. 第三次失败 → 放弃，返回错误

这种策略确保了即使工具定义导致模型出错，Agent 仍然能以纯对话模式继续工作。

### 4. 状态集中存储

所有可变状态挂在 `AIAgent` 实例上（`agent.tools`、`agent.messages`、`agent.session_id` 等），主循环和各层函数通过参数读取/修改它。这种"属性袋"模式使得：
- 状态溯源容易：只需要跟踪 AIAgent 实例的属性变化
- 故障恢复简单：持久化整个 agent 状态即可复原
- 但耦合度高：修改属性名需要同步修改所有读取点

---

## 八、核心代码片段解读

### 循环条件（第 715 行）

```python
while (api_call_count < agent.max_iterations 
       and agent.iteration_budget.remaining > 0) \
       or agent._budget_grace_call:
```

**解读：** 循环有双重限制——`max_iterations`（硬上限）和 `iteration_budget`（软预算）。`_budget_grace_call` 是一个逃生舱：当预算刚好在 tool call 执行过程中耗尽时，允许最后一次"恩典"调用让 LLM 有回复用户的机会。

### 上下文压缩触发（第 1128-1179 行）

```python
if estimated_tokens > agent.max_context_tokens:
    agent._compress_context(messages, ...)
```

**解读：** Hermes 的上下文压缩是在每次 API 调用前**按需触发**的，而非像 Kimi Code 那样在每步都做微压缩。这种策略减少了压缩造成的 prompt cache 失效次数，但也意味着上下文可能在临界值附近反复触发压缩。

### 工具执行入口（第 5055 行）

```python
tool_results = agent._execute_tool_calls(
    agent.convert_tool_calls(assistant_message), 
    messages, 
    ...
)
```

**解读：** `convert_tool_calls()` 将 Provider 格式的 tool_call 转换为 Hermes 内部格式，然后 `_execute_tool_calls()` 执行实际的工具调度。这两步分离使得 Hermes 可以支持不同 Provider 的 tool_call 格式，而在执行层统一处理。

---

*Hermes Read — 2026-07-29 · 源码分析：agent/conversation_loop.py*
