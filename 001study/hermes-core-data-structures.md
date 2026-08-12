# Hermes 核心数据结构字典

> 任务001 扫描产出：核心循环 / 上下文压缩 / 工具系统 三大路径的关键数据结构，
> 讲每个数据结构的**职责** + **内部数据流转**，配套核心方法速查。
> 行号基线：hermes-agent-plus 当前 checkout（2026-08-07，CRLF 行尾）。
> 配套文档：《hermes-core-methods-dictionary.md》（方法参数字典）。

---

## 一、AIAgent —— 整个 Agent 的"总装车间"

- **位置**：`run_agent.py:399`
- **一句话**：持有 Agent 全部运行时状态与子系统的入口对象。
  你可以把它想成"一台机器的机身"——所有部件（循环、预算、压缩、工具、记忆）
  都挂在它身上，`run_conversation()` 是启动按钮。

### 职责

1. 持有全局配置：model / provider / max_iterations（默认 90）/ enabled_toolsets 等
2. 持有全部子系统的引用：iteration_budget、context_compressor、tool_registry、
   消息列表（_session_messages）、会话存储（_session_db）
3. 维护会话级计量：session_total_tokens / session_input_tokens /
   session_output_tokens / session_api_calls / session_estimated_cost_usd 等
4. 维护中断状态：_interrupt_requested / _interrupt_message（用户 Ctrl+C 或 /stop）
5. 提供回调挂载点：tool_progress_callback / stream_delta_callback /
   event_callback 等十几个回调（TUI/WebUI/桌面端都靠这些回调拿事件）

### 内部数据流转（一次完整对话）

```
用户输入
  → run_conversation(agent, user_message, ...)        # conversation_loop.py:588
  → build_turn_context(...)                            # 产出 TurnContext（见下）
  → 主循环 [iteration_budget.consume() 扣预算]         # conversation_loop.py:736
      → _interruptible_api_call()                      # 调 LLM，usage 回填 session_*_tokens
      → finish_reason == 'tool_use'?
          → execute_tool_calls_*()                     # 工具执行（见工具系统）
          → 结果 append 进 messages
      → should_compress()?                             # 超阈值
          → context_compressor.compress(messages)      # 压缩，替换 messages
  → 返回最终回复
```

### 关键字段速查

| 字段 | 含义 |
|------|------|
| max_iterations | 最大工具调用迭代次数（默认 90） |
| iteration_budget | 迭代预算对象（线程安全计数） |
| _session_messages | 当前会话消息列表（核心数据流载体） |
| context_compressor | 上下文压缩引擎（ContextCompressor 实例） |
| _api_call_count | 本回合 API 调用次数 |
| _interrupt_requested | 用户中断标志 |
| session_total_tokens | 会话累计 token（计量/计费） |

---

## 二、IterationBudget —— 迭代预算计数器

- **位置**：`agent/iteration_budget.py:17`
- **一句话**：线程安全的"还能跑几轮"计数器，防止 Agent 无限循环烧钱。

### 职责

1. 计数：consume() 每次迭代扣 1，used >= max_total 后拒绝
2. 退款：refund() 归还 1 次（execute_code 编程式工具调用不占预算）
3. 隔离：父 agent 与每个子 agent 各有独立预算
   （父 90 次，子 agent 按 delegation.max_iterations 默认 50 次）

### 内部数据流转

```
__init__(max_total)  → self.max_total / self._used / self._lock
consume()  → 加锁检查 used < max_total？是则 used+1 返回 True，否则 False
refund()   → 加锁 used-1（不小于 0）
used 属性  → 当前已用次数（供日志/状态展示）
```

### 配套方法

| 方法 | 行号 | 说明 |
|------|------|------|
| consume() | :40 | 消耗一次迭代，返回是否允许 |
| refund() | :52 | 归还一次迭代 |
| used / max_total | :60+ | 只读属性 |

---

## 三、TurnContext —— 单回合上下文快照

- **位置**：`agent/turn_context.py:242`（@dataclass）
- **一句话**：回合"序幕"阶段产出的值，交给"回合循环"消费的**数据包**。
  一次用户输入 = 一个 TurnContext。

### 职责（字段即职责）

| 字段 | 含义 |
|------|------|
| user_message | 规范化后的用户消息文本 |
| original_user_message | 原始用户输入（未清洗版本，保留原始形态） |
| messages | 本回合工作消息列表（循环中不断 append 工具结果） |
| conversation_history | 历史消息（多轮续聊时传入） |
| active_system_prompt | 当前生效的系统提示词 |
| effective_task_id | 生效任务 ID（隔离 VM/上下文） |
| turn_id | 回合唯一 ID |
| current_turn_user_idx | 当前回合用户消息在 messages 中的索引 |
| should_review_memory | 本回合是否需要触发记忆回顾 |
| plugin_user_context | 插件提供的用户上下文附加文本 |
| ext_prefetch_cache | 外部预取缓存（性能优化） |

### 内部数据流转

```
用户输入 → build_turn_context(agent, user_message, ...)   # turn_context.py 工厂函数
  → 组装 TurnContext 数据包
  → run_conversation 主循环读取：messages 增删、system prompt 注入
  → 回合结束：TurnContext 生命周期完成
```

### 配套方法

| 方法 | 行号 | 说明 |
|------|------|------|
| build_turn_context() | turn_context.py（工厂） | 组装回合上下文数据包 |

---

## 四、ContextEngine（ABC）—— 上下文引擎抽象基类

- **位置**：`agent/context_engine.py:32`
- **一句话**：所有上下文引擎必须实现的**统一接口**，定义"上下文怎么管理"的契约。
  目前唯一实现是 ContextCompressor；未来可插 LCM 等其他引擎。

### 职责

1. 定义抽象接口：name（引擎名）、update_from_response()（从 API 响应更新 token 用量）
2. 定义共享状态字段（基类属性，子类继承）：

| 字段 | 含义 |
|------|------|
| last_prompt_tokens | 上次请求 prompt token 数 |
| last_completion_tokens | 上次生成 token 数 |
| last_total_tokens | 上次总 token 数 |
| threshold_tokens | 压缩触发阈值（token） |
| context_length | 模型上下文窗口长度 |
| compression_count | 累计压缩次数 |
| threshold_percent | 触发百分比（默认 0.75） |
| protect_first_n | 头部保护消息数（默认 3） |
| protect_last_n | 尾部保护消息数（默认 6） |

### 配套方法

| 方法 | 行号 | 说明 |
|------|------|------|
| name（abstractmethod） | :36 | 引擎短标识（'compressor'） |
| update_from_response()（abstractmethod） | :80 | 每次 LLM 调用后更新 token 计量 |
| should_compress() / compress() | 子类实现 | 触发判断 / 压缩执行 |

---

## 五、ContextCompressor —— 默认上下文引擎（压缩器）

- **位置**：`agent/context_compressor.py:859`
- **一句话**：ContextEngine 的默认实现，用**有损摘要**压缩超长上下文。
  这就是"上下文压缩"的全部秘密所在。

### 职责

1. 五步压缩算法（剪枝 → 保头 → 保尾 → 中间摘要 → 清理孤儿 tool 对）
2. 维护压缩相关全部状态（见下）
3. 探测模型上下文窗口（get_model_context_length）
4. 摘要失败处理：冷却、回退、连续失败计数

### 核心状态字段（on_session_reset 重置的）

| 字段 | 含义 |
|------|------|
| _previous_summary | 上次摘要（迭代更新基础） |
| _last_summary_error | 上次摘要错误 |
| _consecutive_timeout_failures | 连续超时失败计数 |
| _last_summary_dropped_count | 上次摘要丢弃消息数 |
| _last_compression_savings_pct | 上次压缩节省百分比 |
| _ineffective_compression_count | 无效压缩计数（反抖动用） |
| _summary_failure_cooldown_until | 摘要失败冷却截止时间 |
| last_real_prompt_tokens | 最近真实 prompt token 数 |

### 内部数据流转（一次压缩）

```
should_compress(prompt_tokens)  → 超阈值且非反抖动？        # :1557
  → compress(messages, current_tokens, focus_topic, force)  # :3271
      ├→ _prune_old_tool_results()      # 剪枝旧工具结果（无 LLM 调用）:1649
      ├→ _protect_head_size()           # 保护头部（system+首轮）:2874
      ├→ _find_tail_cut_by_tokens()     # 尾部 token 预算切点 :3148
      ├→ _generate_summary()            # 中间段 LLM 结构化摘要 :2144
      │    └→ 失败 → _build_static_fallback_summary()
      ├→ _align_boundary_forward/backward()  # 切点对齐（不切 tool 组）:2847/:2899
      └→ _sanitize_tool_pairs()         # 清理孤儿 tool 对 :2769
  → 返回压缩后 messages（head + summary + tail）
```

### 配套方法（详见《方法参数字典》）

should_compress :1557 / compress :3271 / _prune_old_tool_results :1649 /
_generate_summary :2144 / _protect_head_size :2874 / _find_tail_cut_by_tokens :3148 /
_sanitize_tool_pairs :2769 / _align_boundary_forward :2847 / _align_boundary_backward :2899

---

## 六、ToolEntry —— 单个工具元数据

- **位置**：`tools/registry.py:87`
- **一句话**：一个已注册工具的"身份证 + 操作手册"。
  __slots__ 声明固定字段（内存优化），12 个字段描述工具全貌。

### 字段（__slots__）

| 字段 | 含义 |
|------|------|
| name | 工具名（模型调用时的标识） |
| toolset | 所属工具集（terminal/file/web/...） |
| schema | OpenAI 工具 schema（name/description/parameters JSON Schema） |
| handler | 实际执行函数（调用签名 args + kwargs） |
| check_fn | 可用性检查（如需要 API key 的工具返回 False 则不暴露） |
| requires_env | 依赖的环境变量列表 |
| is_async | 是否异步处理器 |
| description | 工具描述（进 schema） |
| emoji | 展示用 emoji |
| max_result_size_chars | 结果截断上限（防超大输出撑爆上下文） |
| dynamic_schema_overrides | 动态 schema 覆盖（运行时按需调整参数） |

### 内部数据流转

```
register(name, toolset, schema, handler, check_fn, ...)   # registry.py:365
  → ToolEntry 实例化，挂到 ToolRegistry
  → 模型请求时：get_entry(name) 取 schema → 组装进 API 请求
  → 工具被调用时：handler(args, **kwargs) → 返回 JSON 字符串
  → 结果过大？max_result_size_chars 截断
```

---

## 七、ToolRegistry —— 工具注册中心

- **位置**：`tools/registry.py:217`
- **一句话**：全部工具的"总目录"，管理注册、查询、工具集映射、快照。
  模型能看到哪些工具、调哪个 handler，都由它说了算。

### 职责

1. 注册/查询：register() / get_entry(name)
2. 工具集管理：get_tool_names_for_toolset() / 别名（register_toolset_alias）
3. 快照：_snapshot_state()（工具集切换时保留状态）
4. 插件归属：_plugin_owner_of()（判断工具属于哪个插件模块）
5. 可用性缓存：_check_fn_cached()（check_fn 结果缓存，避免每次检查）

### 内部数据流转

```
启动
  → discover_builtin_tools(tools_dir)          # :67 扫描 tools/*.py 自动发现
  → 各模块 registry.register(...)              # 注册 ToolEntry
  → AIAgent 初始化：enabled_toolsets 过滤 → 模型请求只带启用工具
  → 运行时：get_entry(name) → handler 调用
  → 工具集切换：_snapshot_state() 快照 → 恢复
```

### 配套方法

| 方法 | 行号 | 说明 |
|------|------|------|
| discover_builtin_tools() | :67 | 扫描工具目录自动发现 |
| get_entry(name) | :274 | 按名取工具元数据 |
| register() | :365 | 注册工具 |
| register_toolset_alias() | :290 | 工具集别名 |
| get_tool_names_for_toolset() | :283 | 工具集内工具名列表 |
| _snapshot_state() | :241 | 状态快照 |

---

## 速查：数据结构 → 职责一句话

| 数据结构 | 位置 | 一句话 |
|----------|------|--------|
| AIAgent | run_agent.py:399 | 总装车间：持有全部子系统的 Agent 本体 |
| IterationBudget | iteration_budget.py:17 | 线程安全迭代计数器，防无限循环 |
| TurnContext | turn_context.py:242 | 单回合数据包：序幕产、循环消费 |
| ContextEngine | context_engine.py:32 | 上下文引擎抽象契约（ABC） |
| ContextCompressor | context_compressor.py:859 | 默认引擎：五步有损压缩 |
| ToolEntry | registry.py:87 | 工具身份证：12 字段描述一个工具 |
| ToolRegistry | registry.py:217 | 工具总目录：注册/查询/快照/插件归属 |

---

## 数据流总览（一条主线串起所有结构）

```
用户输入
  │
  ▼
TurnContext（回合数据包）
  │
  ▼
AIAgent.run_conversation() 主循环
  │  ├→ IterationBudget.consume()  ← 预算护栏
  │  ├→ LLM 调用 → usage 回填 AIAgent.session_*_tokens
  │  ├→ tool_use? → ToolRegistry.get_entry(name) → ToolEntry.handler 执行
  │  │                → 结果 append 进 messages（回合数据流）
  │  └→ 超阈值? → ContextCompressor.compress(messages)
  │                → ContextEngine 状态字段更新（compression_count 等）
  ▼
最终回复
```
