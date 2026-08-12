# Context Compression 上下文压缩研究

> 001 任务(Hermes 探索)子目录 —— Hermes Run Conversation 的上下文工程（与核心循环分析、Hermes Read 同源）
> 源码研究基于 `/root/projects/hermes-agent-plus/`（禁止读 venv 安装版）
> 行号均为 hermes-agent-plus 当前 checkout 的精确位置
>
> **演示产出已迁移**：独立可运行的复刻 demo 现在在
> `/root/projects/demo-context-compress/`（context_compressor.py + README.md，
> 含原理与完整源码映射）。本文档保留研究结论（触发点/配置对照/设计细节）。

## 调用链

```
run_conversation (conversation_loop.py:588)
  └─ agent._compress_context(...)        ← 6 处调用点
       └─ AIAgent._compress_context (run_agent.py:6112)   ← 转发器
            └─ compress_context (agent/conversation_compression.py:592)  ← 总编排
                 ├─ 会话锁（state.db 原子锁，防并发压缩产生孤儿会话）: conversation_compression.py:691-732
                 ├─ 反抖动/冷却守卫（force=False 时）: :643-654
                 ├─ 懒可行性检查（aux provider 探测）: :663-670
                 ├─ in_place 模式（不换 session_id，config: compression.in_place）: :673-679
                 └─ ContextCompressor.compress (context_compressor.py:3271)  ← 五步算法
```


---

## 0. 结论：三种策略全都有，但分层混合

| 猜测策略 | 是否采用 | 位置 | 说明 |
|---|---|---|---|
| 1. 截断/暴力丢弃 | ⚠️ 只作辅助 | `_prune_old_tool_results` + `_build_static_fallback_summary` | 主路径从不裸删。a) 工具结果预扫描：完整输出换成一行语义摘要；b) LLM 摘要失败：插入确定性锚点回退，不是 "N 条已删" 空标记 |
| 2. AI 压缩 | ✅ 主策略 | `_generate_summary` | 结构化 prompt（Goal/Constraints/Completed Actions/Active State/未完成任务快照）调 auxiliary LLM，可配独立小模型，迭代式增量更新 |
| 3. 滑动窗口 | ✅ 以"保头保尾"形式存在 | `_find_tail_cut_by_tokens` | 头部固定保护（system + protect_first_n）+ 尾部按 token 预算从尾往回开窗；窗口内的中间段全部摘要掉。不是丢尾部，是保留头尾、压缩中间 |

一句话：**保头（固定） + 保尾（token 预算滑动窗口） + 中间段 AI 摘要**，暴力丢弃只在预剪枝和失败回退两个辅助位出现。

---

## 1. 五步算法 → 源码映射 → demo 对照

主算法注释在 `agent/context_compressor.py:3273-3282`（`compress()` 的 docstring 即算法文档）。

| 步骤 | 源码函数 | 源码位置 | demo 函数（context_compression_minimal.py） |
|---|---|---|---|
| 0. 触发判断 | `should_compress` | `agent/context_compressor.py:1557` | `should_compress` |
| 1. 剪枝旧工具结果 | `_prune_old_tool_results` | `agent/context_compressor.py:1649` | `_prune_old_tool_results` |
| 2. 保护头部 | `_protect_head_size` | `agent/context_compressor.py:2874` | `_protect_head_size` |
| 2b. 边界对齐（不切 tool 组） | `_align_boundary_forward` / `_align_boundary_backward` | `:2847` / `:2899` | `_align_boundary_forward` / `_align_boundary_backward` |
| 3. 尾部 token 预算窗口 | `_find_tail_cut_by_tokens` | `agent/context_compressor.py:3148` | `_find_tail_cut_by_tokens` |
| 3b. 最后 user/assistant 消息保底 | `_ensure_last_user_message_in_tail` / `_ensure_last_assistant_message_in_tail` | `:3047` / `:2989` | 内联在 `_find_tail_cut_by_tokens` 尾部 |
| 4. LLM 结构化摘要 | `_generate_summary` | `agent/context_compressor.py:2144` | `_generate_summary`（默认本地规则，可注入 LLM 回调） |
| 4b. 摘要预算/序列化 | `_compute_summary_budget` / `_serialize_for_summary` | `:1815` / `:1835` | 简化（token 估算） |
| 4c. 失败 → 静态回退 | `_build_static_fallback_summary` | `agent/context_compressor.py:1923` | `_build_static_fallback_summary` |
| 5. 孤儿 tool pair 清理 | `_sanitize_tool_pairs` | `agent/context_compressor.py:2769` | `_sanitize_tool_pairs` |
| 5b. 组装 + 角色交替修正 | `compress` 后半段 | `:3548-3630+` | `compress` Phase 5 |

### 压缩器类与配置

| 项 | 源码位置 | 默认值 |
|---|---|---|
| `class ContextCompressor(ContextEngine)` | `agent/context_compressor.py:859` | — |
| 抽象基类 `class ContextEngine(ABC)` | `agent/context_engine.py:32` | — |
| `__init__` 全部参数 | `agent/context_compressor.py:1306-1322` | threshold_percent=0.50, protect_first_n=3, protect_last_n=20, summary_target_ratio=0.20 |
| ratio clamp [0.10, 0.80] | `:1331` | — |
| 阈值计算 `_effective_threshold_percent`（<512K 模型强制 ≥0.75） | `:1249` | — |
| 阈值计算 `_compute_threshold_tokens`（预留 max_tokens 输出空间） | `:1266` | — |
| `tail_token_budget = threshold × target_ratio` | `:1375-1376` | — |
| `max_summary_tokens = min(context_length×5%, 10_000)` | `:1377-1379` + `_SUMMARY_TOKENS_CEILING` `:275` | — |
| 尾部消息下限 `_MAX_TAIL_MESSAGE_FLOOR = 8` | `:307` | — |
| 反抖动：连续 2 次无效压缩暂停 | `:1628-1642` | — |
| summary-LLM 失败冷却 | `:1611-1627` | — |

---

## 2. run_conversation 内的触发点（6 处）

| 触发点 | 源码位置 | 时机 |
|---|---|---|
| turn 开头 preflight | `agent/turn_context.py:651` | 每条用户消息进来后、首次 API 调用前 |
| Pre-API 压力检查 | `agent/conversation_loop.py:1128-1155` | 工具循环内每次 API 调用前（工具结果可能瞬间撑爆），每轮最多 3 次（`compression_attempts < 3`） |
| 错误处理路径 1 | `agent/conversation_loop.py:3271-3300` | 上下文超限类错误（413 等） |
| 错误处理路径 2 | `agent/conversation_loop.py:3555` | 同上其他分支 |
| 错误处理路径 3 | `agent/conversation_loop.py:3796` | 同上其他分支 |
| post-response 检查 | `agent/conversation_loop.py:5136-5145` | 每轮响应后，用 API 上报的真实 `last_prompt_tokens` 判断（`should_compress(:5136)`），只数 prompt_tokens 不算 completion（推理 token 会误触发，见 `:5116-5121`） |


---

## 3. 配置项对照（config.yaml → 解析 → 压缩器）

配置段：`cli-config.yaml.example:406-442`（`compression:`）
解析代码：`agent/agent_init.py:1647-1657`（读值）、`:1912-1915`（构造 ContextCompressor）、`:1932`（挂 `agent.compression_enabled`）

| yaml 键 | 默认 | agent_init.py 解析 | 注入 ContextCompressor 参数 |
|---|---|---|---|
| `compression.enabled` | true | `:1647` | → `agent.compression_enabled`（conversation_loop.py:1129/5136 判据） |
| `compression.threshold` | 0.50 | `:1631-1643`（`_resolve_compression_threshold`，含模型族自动抬升） | `threshold_percent` |
| `compression.target_ratio` | 0.20 | `:1648` | `summary_target_ratio` |
| `compression.protect_last_n` | 20 | `:1649` | `protect_last_n` |
| `compression.protect_first_n` | 3 | `:1650-1657`（floor 0） | `protect_first_n` |
| `compression.abort_on_summary_failure` | false | `:1659` 附近 | `abort_on_summary_failure`（true=摘要失败整个中止不丢消息） |
| `compression.codex_app_server_auto` | native | — | codex 运行时走 `_compress_context_via_codex_app_server`（conversation_compression.py:1335） |
| `compression.in_place` | false | `:1932` 附近 | 原地压缩不旋转会话 |
| `auxiliary.compression.provider/model` | 无 | — | 摘要用独立小模型（`summary_model_override`，context_compressor.py:1314） |

---

## 4. 设计细节（值得记住的工程决策）

1. **反抖动**：`should_compress` 记 `_ineffective_compression_count`，连续 2 次压缩节省 <10% 就暂停（context_compressor.py:1628-1642），否则死循环（#40803 系列修复）。
2. **失败分级**：摘要 LLM 失败时——普通失败 → 静态回退继续（保可用性）；401/402/403/配额 → 整个中止不丢数据（`abort_on_summary_failure` 与 `_last_summary_auth_failure` 分支，:3509-3546）；网络瞬断 → 中止等恢复。
3. **不切 tool 组**：`_align_boundary_*` 保证 assistant(tool_calls) 和 tool 结果永远同侧，否则 API 报 mismatched id。
4. **角色交替**：压缩后 summary 的 role 要避开与头尾相邻消息同 role（Anthropic 拒绝首条非 user；OpenAI 兼容后端拒绝零 user 消息），:3576-3630。
5. **最后消息保底**：最后一条 user 消息（#10896）和最后一条 assistant 消息（#29824）必须留在尾部。
6. **会话锁**：压缩会旋转 session_id（除非 in_place），并发压缩会 fork 出孤儿会话，用 state.db 原子锁防并发（conversation_compression.py:691-732）。
7. **摘要注入防护**：summarizer prompt 明确"只当素材不当指令"，密钥一律 REDACT（context_compressor.py:2222-2225）；memory provider 上下文按 JSON 字符串隔离（:2187-2196）。
8. **时间锚定**：摘要要求把相对表述改写为带日期的过去时，防止恢复会话后重复执行已完成动作（:2233-2244）。

---

## 5. demo 使用

```bash
cd /root/projects/demo-context-compress
python3 context_compressor.py
```

- 默认 `summarize_fn=None` → 本地规则摘要（无需 API）；传真实 LLM 回调即等价源码 auxiliary 摘要路径
- 演示场景：33 条消息 ≈12.6K tokens，超过 20K×50%=10K 阈值自动触发；压缩 33→14 条、token 省 81%
- 失败回退演示：注入返回 None 的 summarize_fn → 走 `_build_static_fallback_summary`
- 触发拒绝演示：8 条短对话低于阈值 → `should_compress=False`
