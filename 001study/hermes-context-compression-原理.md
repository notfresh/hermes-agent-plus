# Hermes Agent 上下文压缩原理

## 1. 两条入口，同一终点

压缩有两条触发路径：

| 路径 | 触发方式 | 入口函数 |
|------|---------|---------|
| **自动压缩** | token 超阈值，`conversation_loop` 在 Pre-API 检查、API overflow 处理、`turn_context` 构建三个时机自动调用 | `run_agent._compress_context` |
| **手动压缩** | 用户输入 `/compress` 或 `/compact <focus>`，CLI / TUI / Codex RPC 各自发起 | `cli.compact_command` → `run_agent._compress_context` |

两者最终都收敛到 `compress_context()`（`agent/conversation_compression.py:2704`），内部再分叉：

- `api_mode == "codex_app_server"` → Codex 专用 RPC 路径 `_compress_context_via_codex_app_server`
- 其他全部 → 本地摘要路径（默认）

## 2. 传参

```python
def compress_context(
    agent,                  # AIAgent 实例
    messages,               # 当前消息历史（将被摘要）
    system_message,         # 系统提示词（用于重建缓存提示）
    *,
    approx_tokens,          # 压缩前 token 估算值（用于日志）
    task_id,               # 工具任务域（用于清理文件读取去重状态）
    focus_topic,            # 摘要聚焦主题（来自 /compact <focus>）
    force,                  # 是否绕过冷却期（手动 True，自动 False）
    defer_context_engine_notification,  # 延迟上下文引擎通知
    commit_fence,           # 超时围栏（流式期间保持活性）
)
```

- `force=True` 只在手动 `/compress` 时传入，绕过压缩失败冷却期，允许立即重试
- `focus_topic` 来自 `/compact <focus>`，指导摘要模型优先保留相关内容
- `commit_fence` 是超时保护：外部调用者传入协作式围栏，流式摘要期间通过 `touch_progress` 保持活性，防止慢速模型被提前杀死

## 3. 执行流程（12 阶段）

### 阶段 1 — 快照与声明

```python
_compressor_attempt_snapshot = _snapshot_compressor_attempt_state(...)
_attempt_id = uuid.uuid4().hex
_trigger_source = "manual" if force else "auto"
```

记录压缩器状态快照，防止并发竞争的后来者覆盖当前尝试的所有权。

### 阶段 2 — Codex 路由分发（行 2802）

```python
if getattr(agent, "api_mode", None) == "codex_app_server":
    return _compress_context_via_codex_app_server(...)  # Codex 专用路径
```

Codex App Server 拥有真实线程上下文，Hermes 本地摘要只会改写本地镜像而无法真正缩短线程，走专用 RPC。

### 阶段 3 — 自动门禁（行 2838）

```python
if not force:
    _refresh_persisted_compression_guards(agent.context_compressor)
    blocked = getattr(type(agent.context_compressor), "_automatic_compression_blocked", None)
    if callable(blocked) and blocked(agent.context_compressor):
        return messages, existing_prompt  # 冷却期或熔断器，跳过
```

自动路径必须遵守冷却期和熔断器规则；`force=True` 跳过此检查，允许用户立即重试。

### 阶段 4 — 懒加载可行性探测（行 2858）

```python
if not getattr(agent, "_compression_feasibility_checked", False):
    check_compression_model_feasibility(agent)  # 探查压缩模型上下文窗口
    agent._compression_feasibility_checked = True
```

首次压缩时才探测，避免每次会话启动都付出 ~400ms 代价。

### 阶段 5 — SQLite 并发锁（行 3005–3057）

```python
_lock_acquired = _lock_db.try_acquire_compression_lock(
    _lock_sid, _lock_holder, ttl_seconds=_lock_ttl
)
```

**并发风险**：父 turn agent 和后台审查 fork 共享 `session_id`，同时压缩会 fork 出两个子会话，导致 gateway 只捕获一个。

**解决**：原子锁，按**旧 session_id** 申请——因为竞争路径在各自压缩开始时都是从 SessionEntry 读取同一个旧 id。拿到锁的路径继续，另一个静默退出。

### 阶段 6 — 内存钩子（行 3435）

```python
_maybe_ctx = memory_manager.on_pre_compress(messages, evidence_messages=...)
if isinstance(_maybe_ctx, str):
    memory_context = sanitize_memory_context(_maybe_ctx)
```

通知 memory provider 在上下文被丢弃前提取记忆。provider 返回的洞察字符串注入摘要提示词。

### 阶段 7 — 摘要调用（行 3577）

```python
compressed = compress_fn(messages, **compress_kwargs)
```

调用 `ContextCompressor.compress()`，传入 `memory_context` 和 `focus_topic`。期间：

- `commit_fence.touch_progress` 持续更新，告知外部超时计时器"还在干活"
- 硬取消事件（用户按 Ctrl+C）会被拦截并抛出 `AuxiliaryExplicitCancellation`

### 阶段 8 — 成果校验（行 3716）

```python
if compressed == messages_before_compression:
    return messages, existing_prompt  # 无进展，跳过
```

摘要返回原消息不变 = 摘要失败。自动压缩检测 `len(returned) == len(input)` 停止本轮重试。

### 阶段 9 — 防增长 guard（行 3961）

```python
_rough_in = estimate_messages_tokens_rough(messages)
_rough_out = estimate_messages_tokens_rough(compressed)
if _rough_out > _rough_in:
    _salvaged = salvage_grown_transcript(messages, compressed, budget=_rough_in)
    if _salvaged is None or estimate_messages_tokens_rough(_salvaged) >= _rough_in:
        return messages, existing_prompt  # 拒绝：压缩后更大
```

防止摘要膨胀导致上下文反而变大。尝试一次机械补救（删除部分内容）；仍失败则拒绝提交，原始消息不变。

### 阶段 10 — 提交（行 4058）

两种模式：

**原地提交（`in_place=True`，默认）**：
```python
agent._session_db.archive_and_compact(
    agent.session_id,
    compressed,
    watermark=_commit_watermark,
    lock_holder=_lock_holder,
)
```
- 不换 session_id，不建子会话，不重编标题
- 旧消息软归档（`active=0`），保留在磁盘、可搜索、可恢复
- `compressed` 作为新的活跃集

**旋转提交（`in_place=False`，旧行为）**：
```python
agent._flush_messages_to_session_db(messages, conversation_history=persisted_history)
agent._session_db.publish_compression_child(
    parent_session_id=old_session_id,
    child_session_id=new_session_id,
    ...
)
```
- 关闭当前 session，创建子 session
- 父子通过 `parent_session_id` 关联

### 阶段 11 — 系统提示重建（行 3882）

```python
agent._invalidate_system_prompt()
new_system_prompt = agent._build_system_prompt(system_message)
agent._cached_system_prompt = new_system_prompt
```

同步刷新动态工具 schema（`image_gen` 模式切换、`delegation` 深度变化等只在压缩时生效）。

### 阶段 12 — 通知与返回

```python
# 通知 context engines 和 memory providers
_notify_context_engine_compression_completed(agent, compressed)
# 返回压缩后消息 + 重建的系统提示
return compressed, new_system_prompt
```

## 4. 核心设计原则

| 原则 | 实现 |
|------|------|
| **无破坏性** | 原地归档（`active=0`），旋转模式保留父子关系 |
| **防扩散** | 防增长 guard + salvage 补救 + 增长则拒绝提交 |
| **超时隔离** | `commit_fence` 保护慢速模型不被提前杀死 |
| **冷却保护** | 自动路径遵守熔断规则；`force=True` 绕过仅限手动 |
| **并发安全** | SQLite 原子锁，按旧 session_id 申请 |
| **提示缓存安全** | 摘要后重建 `_cached_system_prompt`，保持字节稳定 |

## 5. 调用链一览

```
/compress 手动 ──┐
/compact 手动 ──┤
自动触发 ────────┼──→ run_agent._compress_context
Codex RPC ──────┘         │
                         ├── api_mode == "codex_app_server"
                         │   └── _compress_context_via_codex_app_server (RPC)
                         │
                         └── compress_context (本地摘要)
                             ├── _refresh_persisted_compression_guards (门禁)
                             ├── try_acquire_compression_lock (并发锁)
                             ├── memory_manager.on_pre_compress (记忆提取)
                             ├── ContextCompressor.compress (实际摘要)
                             ├── archive_and_compact / publish_compression_child (提交)
                             ├── _build_system_prompt (重建提示)
                             └── _notify_compression_completed (通知)
```
