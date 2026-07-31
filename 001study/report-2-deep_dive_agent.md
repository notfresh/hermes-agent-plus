# Report 2: Agent 内部架构深度分析

## 概览

`agent/` 目录包含 156 个文件，是从 `run_agent.py` 这块 God File 逐步提取出来的模块。核心原则：通过提取纯函数和自包含类让 `run_agent.py` 瘦身，同时保持对现有测试 patch 的兼容（通过 `_ra()` 懒引用模式）。

## 核心架构图谱

```
run_agent.py (AIAgent 类)
  └─ agent_init.py          # AIAgent.__init__ 提取 (2200行)
  └─ conversation_loop.py   # run_conversation 主体 (5780行)
      ├─ turn_context.py    # 每轮的序章逻辑 (902行)
      ├─ turn_finalizer.py  # 每轮的收尾逻辑
      ├─ turn_retry_state.py # 重试状态机
      ├─ tool_executor.py   # 工具调用执行 (1801行)
      ├─ tool_dispatch_helpers.py # 并行调度、文件变异追踪等 (653行)
      ├─ tool_guardrails.py # 工具调用循环防护 (479行)
      ├─ tool_result_classification.py # 工具结果分类
      └─ message_sanitization.py # 消息清理
  ├─ conversation_compression.py # 对话压缩
  ├─ context_compressor.py  # 上下文窗口压缩 (3673行)
  ├─ auxiliary_client.py    # 辅助LLM路由 (8036行)
  ├─ credential_pool.py     # 多凭证池 (2600行)
  ├─ credential_persistence.py # 凭证持久化
  ├─ credential_sources.py  # 凭证来源检测
  ├─ memory_manager.py      # 内存管理器 (1231行)
  ├─ memory_provider.py     # 内存提供器接口(ABC)
  ├─ prompt_builder.py      # 系统提示词组装 (2066行)
  ├─ system_prompt.py       # 系统提示词构建
  ├─ model_metadata.py      # 模型元数据管理
  ├─ iteration_budget.py    # 迭代预算
  └─ display.py             # KawaiiSpinner 显示引擎
```

## 关键设计模式

### 1. 提取 + 懒引用模式 (`_ra()`)

从 `run_agent.py` 提取出去的所有模块都通过 `_ra()` 懒引用回 `run_agent`：

```python
def _ra():
    """Lazy reference to run_agent so callers can patch
    run_agent.handle_function_call / run_agent._set_interrupt"""
    import run_agent
    return run_agent
```

这保证了测试中用 `@patch("run_agent.handle_function_call", ...)` 的写法不需要改变。提取出去的函数通过 `_ra().handle_function_call(...)` 调用，patch 依然生效。

### 2. `__init__.py` 几乎是空的

只导入了 `jiter_preload`，其他模块都不在这里导入。所有模块靠它们被 `run_agent.py`、`conversation_loop.py` 等显式 import，或者被 `model_tools.py` 导入。`agent/` 目录更像一个"命名空间包"而非一个严格封装的 Python 包。

### 3. Turn 生命周期

每轮对话拆分为三个清晰阶段：

**序章 (Prologue) — `turn_context.build_turn_context()`**
- Stdio 守卫、运行时线程绑定
- 用户消息消毒（surrogates、非ASCII）
- TODO/nudge 计数器重置
- 系统提示词恢复或重建
- 预检上下文压缩
- 插件 `pre_llm_call` 钩子
- 外部内存预取
- 崩溃韧性持久化
- 返回 `TurnContext` 数据类

**主循环 (Main Loop) — `conversation_loop.run_conversation()`**
```python
while (api_call_count < max_iterations and iteration_budget.remaining > 0) or grace_call:
    # 检查中断
    if interrupt_requested: break
    # 消费预算
    budget.consume()
    # API调用
    response = client.chat.completions.create(...)
    # 处理工具调用
    if response.tool_calls:
        handle_tool_calls(...)
    else:
        return final_response
```

**收尾 (Finalizer) — `turn_finalizer`**
- 保存轨迹
- 内存同步
- 技能维护检查
- 投递异步事件

### 4. 工具执行

`tool_executor.py` 支持两种模式：

- **顺序执行** (`_execute_tool_calls_sequential`): 工具一个一个跑，结果逐一添加到消息列表后继续
- **并发执行** (`_execute_tool_calls_concurrent`): 并行安全的工具（只读工具、非冲突的文件工具）可以同时跑，最多 8 个 worker

并行逻辑在 `tool_dispatch_helpers.py` 中：
- `_NEVER_PARALLEL_TOOLS`: clarify（永远不能并行）
- `_PARALLEL_SAFE_TOOLS`: read_file, web_search 等只读工具
- `_PATH_SCOPED_TOOLS`: read_file/write_file/patch 在路径不冲突时可并行
- `_DESTRUCTIVE_PATTERNS`: 终端命令的破坏性启发式判断

### 5. 工具调用防护 (`tool_guardrails.py`)

纯副作用-free 的控制器，跟踪每轮的工具调用模式：
- 相同连续失败检测（warn after 2, block after 5）
- 同一工具重复失败检测（warn after 3, halt after 8）
- 无进展检测（warn after 2, block after 5）
- 幂等工具集合 vs 变异工具集合

### 6. 凭证系统 (`credential_pool.py`)

多凭证池实现同提供者故障转移：
- `STATUS_OK` / `STATUS_EXHAUSTED` / `STATUS_DEAD` 三级状态
- 40+ 种终端认证失败模式
- OAuth 令牌过期检测
- 自定义提供者（MODEL_CONFIGS in config.yaml）支持
- OpenRouter 同密钥多个模型的独立状态追踪

### 7. 辅助 LLM 路由 (`auxiliary_client.py`)

8036 行的路由引擎，为侧任务选择最佳 LLM 后端：
- **文本任务** 自动探测链：主提供者 → OpenRouter → Nous Portal → 自定义端点 → Anthropic → 直接 API 提供者
- **视觉任务** 自动探测链：主提供者(需支持视觉) → OpenRouter → Nous Portal → Anthropic → 自定义端点
- 每任务覆盖 (`auxiliary.<task>.model`) 在 config.yaml 中
- 402 错误自动降级到下一个提供者

### 8. 记忆管理器 (`memory_manager.py`)

只允许一个外部内存提供者同时激活（防止工具架构膨胀），提供：
- `build_system_prompt()` — 构建内存系统的系统提示词
- `prefetch_all()` — 预取相关记忆
- `sync_all()` — 每轮同步记忆
- `queue_prefetch_all()` — 异步预取

### 9. 上下文压缩 (`context_compressor.py`)

当对话超长时自动压缩中间轮次，保护首尾上下文：
- 结构化摘要模板（已解决/待决问题追踪）
- 令牌预算尾部保护
- 工具输出预剪枝
- 累积摘要（多次压缩之间保留信息）
- 可缩放摘要预算（与压缩内容成比例）

## 文件大小统计

| 文件 | 行数 | 说明 |
|------|------|------|
| `auxiliary_client.py` | 8036 | 辅助LLM路由 — 最大的提取模块 |
| `conversation_loop.py` | 5780 | 核心对话循环 |
| `context_compressor.py` | 3673 | 上下文压缩引擎 |
| `credential_pool.py` | 2601 | 多凭证池 |
| `agent_init.py` | 2200 | AIAgent.__init__ 提取 |
| `prompt_builder.py` | 2066 | 系统提示词构建 |
| `tool_executor.py` | 1801 | 工具调用执行 |
| `memory_manager.py` | 1231 | 内存管理器 |
| `turn_context.py` | 902 | 每轮序章 |
| `turn_finalizer.py` | ~600 | 每轮收尾 |

## 疑问点

1. `auxiliary_client.py` 有 8036 行，是所有提取模块中最大的——是否还有进一步提取空间？
2. `agent/` 目录的 `__init__.py` 几乎空着，如果改成真正的命名空间包，会不会更清晰？
3. 对话循环中的 `build_turn_context` 仍会大量修改 agent 对象——纯函数提取能覆盖，但"side effect 在哪里"还不太容易追踪
4. `credential_pool.py` 与 `hermes_cli/auth.py` 之间的职责边界有点模糊，两者都处理凭证轮换

## 下一步

- **Phase 3**: deep_dive_tools — 探索 tools/ 目录的工具注册/分发/执行机制
