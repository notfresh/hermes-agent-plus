# Teach 13：消息防呆——agent 发请求前的最后一道体检（repair + sanitize）

> 关联上游 issue：#77921（P1，"empty tool_calls after repair_message_sequence"——修了又复发的消息格式 bug）
> 关联模块：`agent/agent_runtime_helpers.py`、`agent/conversation_loop.py`、`run_agent.py`
> 前置知识：teach-3（tool 系统）、teach-12（迭代预算）

---

## 第一层：直觉——寄信前你会不会检查一遍？

想象你要寄一封信，邮局有个霸王规定：**"收件人"和"寄件人"必须严格轮流出现**，不能连着两封信都是你寄的，也不能寄出一封没有收件人的信。违反一条，整封信退回，还罚你重写。

Agent 给模型发请求，就是这个场景。模型 API（尤其 DeepSeek、Kimi 这类严格实现）要求消息数组**严格交替**：`user → assistant → tool → assistant → user → ...`。任何一条"畸形"消息——比如：

- 连续两条 assistant 消息
- 一条 `tool` 结果消息，前面却没有对应的 assistant 工具调用
- 一个 `tool_calls: []` 空数组

——都会让 API 直接甩一个 HTTP 400 回来。更糟的是，**一旦 400，整个会话可能就卡死了**：重试多少次都是同一个错误（#77921 里报的正是这个：467 条消息的长会话，从第 400 条起永久卡死）。

所以 Hermes 在把消息送上 API 之前，安排了两道"体检"：

1. **`repair_message_sequence`** —— 外科手术：把畸形结构**修好**（合并、丢弃、拼接）
2. **`sanitize_api_messages`** —— 最后安检：在**发出前的最后一毫秒**把所有残留问题清掉

这一篇我们就来看这两道防线长什么样、为什么需要两道、以及 #77921 这个 bug 是怎么从两道防线之间溜过去的。

> 🤔 **思考题**：你觉得"修复"和"安检"是同一个动作，还是必须分开？如果是你设计，会只留一道吗？

---

## 第二层：动手——跟着消息走一遍体检

我们模拟一段"病恹恹"的消息历史，看两道防线怎么处理它。假设消息数组长这样：

```python
messages = [
    {"role": "user", "content": "帮我查一下今天的天气"},
    {"role": "assistant", "content": "好的，我来查", "tool_calls": [
        {"id": "call_1", "function": {"name": "get_weather", "arguments": "{}"}}
    ]},
    # 病 ①：又一条 assistant，跟前一条紧挨着（缺了 tool 结果）
    {"role": "assistant", "content": "稍等，正在查询", "tool_calls": []},   # ← 空数组！
    {"role": "tool", "tool_call_id": "call_1", "content": "晴，25°C"},
    {"role": "tool", "tool_call_id": "call_999", "content": "孤儿结果"},     # ← 病 ②：没人调过 call_999
    {"role": "user", "content": "再帮我看看明天"},
    {"role": "user", "content": "顺便查下空气质量"},                          # ← 病 ③：连续两条 user
]
```

**第一道：`repair_message_sequence`** 按三个 pass 处理：

| Pass | 干什么 | 处理上面哪条 |
|---|---|---|
| Pass 0 | 合并**连续 assistant**：tool_calls 取并集、content 拼接 | 病 ① → 两条合成一条 |
| Pass 1 | 丢弃**没有对应 assistant 调用的 tool 结果** | 病 ② → call_999 那条被扔掉 |
| Pass 2 | 合并**连续 user**（用换行拼接，内容不丢） | 病 ③ → 两条并一条 |

注意 Pass 0 的一个细节：合并时，如果后一条的 `tool_calls` 是**空数组** `[]`，它会原样保留在存活的那条上（代码注释里明说了："preserves a pre-existing `[]` on the surviving turn"）。也就是说——**repair 自己可能制造出 `tool_calls: []`**！

这正是 #77921 的源头：32 条历史消息的 `tool_calls` 是 NULL（存库时没写），加载时变成了 `[]`，repair 一合并，`[]` 跟着存活下来，一路送到 API……然后 DeepSeek 400 了。

**第二道：`sanitize_api_messages`** 就是为这个兜底的——它专门有一条规则：**assistant 消息上挂着空数组/非法值的 `tool_calls`，直接删掉这个键**（语义上等于"没有工具调用"）：

```python
if (
    isinstance(msg, dict)
    and msg.get("role") == "assistant"
    and "tool_calls" in msg
    and not (isinstance(msg["tool_calls"], list) and msg["tool_calls"])
):
    msg = {k: v for k, v in msg.items() if k != "tool_calls"}
    dropped_empty_tool_calls += 1
```

删掉后 `tool_calls` 键不复存在，严格 API 就满意了。issue 作者实测：把 repair 后的消息直接喂给 sanitizer，**32/32 全部清理干净**。那 bug 为什么还在？

> 🤔 **思考题**：体检能查出所有病，但病人还是发病了——问题可能出在哪儿？（提示：体检是在**哪一刻**做的？是不是每条发送路径都做了？）

---

## 第三层：为什么——两道防线，各管各的账

设计上有个微妙分工：

- **`repair_message_sequence` 改的是"病历"**。它原地改写 `messages`（`messages[:] = merged`），改完的结果会**持久化**进会话库、下次恢复时用。它是"把历史修正"。
- **`sanitize_api_messages` 只改"寄出去的复印件"**。它对每条消息做**浅拷贝**（`{k: v for k, v in msg.items() ...}`），删键只删副本，**绝不碰存储里的历史**。

为什么要这么分？看 sanitize 注释里那句关键的话：

> *"do it HERE on the per-call copy rather than in repair_message_sequence, which would destructively rewrite the persisted trajectory. Shallow-copy the message before dropping the key so stored history (and prompt caching) stays byte-stable."*

两个理由：

1. **持久化历史要完整**。`tool_calls: []` 虽然 API 不收，但它是"这条 assistant 消息确实调过工具（虽然没调成）"的真实记录。删掉就丢信息了。存储里留原样，发送时净化——各得其所。
2. **Prompt caching 是命根子**（AGENTS.md 第一条铁律！）。如果每次发送前都改写历史，缓存的 prefix 就失效了，每个 turn 都得重新付费。sanitize 在副本上操作，历史字节不变，缓存才能命中。

所以两道防线不是冗余，是**分工**：repair 管"历史正确性"，sanitize 管"发送合规性"。

> 🤔 **思考题**：如果当初图省事，把空数组清理直接写进 repair（改历史），会发生什么？（想想：用户界面显示的历史、token 缓存、以及 issue 里的场景……）

---

## 第四层：细节——真实代码里的关键权衡

### 1. sanitize 的顺序敏感

`sanitize_api_messages` 不是一次扫描，是**多趟**：先过滤角色白名单 → 删空 tool_calls → 修空 function.name → 再收集"存活的 call_id"集合 → 丢孤儿结果 → 补 stub 结果 → 去重。为什么不能一趟搞定？因为**后一趟的判断依赖前一趟的结果**：比如"哪个 tool 结果是孤儿"要等"哪些 assistant 调用活下来了"才知道。

### 2. 主循环里 sanitize 的位置

看 `conversation_loop.py` 的发送前顺序（约 1011-1035 行）：

```python
if agent._use_prompt_caching:
    api_messages = apply_anthropic_cache_control(api_messages, ...)   # ① 打缓存标记
api_messages = agent._sanitize_api_messages(api_messages)             # ② 最后安检
api_messages = agent._drop_thinking_only_and_merge_users(api_messages)  # ③ 删 thinking-only
```

注意顺序：sanitize 在缓存标记**之后**——因为 sanitize 可能删掉 `tool_calls` 键（消息内容变化），如果先 sanitize 再打缓存标记，标记就是打在"将要用"的最终形态上，缓存更准。而 ③ 在 ② 之后，说明**sanitize 之后还有一步会改消息**——任何一步之后都不该再有"产生畸形消息"的路径。

### 3. 但 #77921 的教训：防呆只在"走过的路"上有效

issue 作者的关键推理是：*"The sanitizer works, which means the failing request is **not passing through `sanitize_api_messages`** on its send path, or the messages are rebuilt after sanitization."*

也就是说：主循环和摘要路径都有 sanitize，但 **WebUI 流式路径（`api/streaming.py` → `run_conversation`）可能在某处手搓了消息、绕过了安检**——LRU 缓存里重建的 AIAgent 实例，也许走了一条没挂 sanitizer 的发送路径。体检做得再好，病人没来体检也没用。

这揭示了一个通用教训：**防御性检查必须挂在"所有"入口上，否则就是"防君子不防小人"**。Hermes 用"统一入口 + 最后关卡"模式（所有 API 调用最终都过 transport 层），但只要有一条旁路，防线就有洞。

> 🤔 **思考题**：如果你是维护者，怎么**验证**"所有发送路径都过了 sanitize"？写测试要测什么才能防止"加了新路径忘了挂安检"这种回归？

---

## 第五层：关联——跟之前学的串起来

- **teach-12（迭代预算）**：那次讲的是"失败扣预算、fallback 链饿死"——预算系统管**次数**，repair/sanitize 管**质量**。两者都是"发送前防呆"，只是防的东西不同：一个防"空转"，一个防"畸形"。
- **prompt caching 铁律（AGENTS.md）**：sanitize 的浅拷贝设计直接为缓存服务——"历史字节稳定"是 Hermes 的第一优先级，所有"发送前净化"都只能发生在副本上。
- **插件系统的注册模式（teach-4）**：你发现没有？"统一注册表 + 最后关卡"在 Hermes 里反复出现——工具注册、插件发现、消息净化，全是"窄腰 + 边缘扩展"哲学的体现。
- **curator（技能维护）**：等我们后面讲 curator 时你会发现，它的"存档前先复核"也是同一类"防呆"思路——**系统越复杂，越要在关键边界设检查点**。

**延伸思考**：#77921 目前还 open、P1、无人认领——但它的修复点不在 repair/sanitize 本身（它们都对），而在**找到那条漏过安检的旁路**。这种"找洞"型 bug 比"补丁"型难：你得先画出完整的发送路径图。你想不想下一期就用这个 issue 当案例，把 `run_conversation → 各 transport 路径` 的完整调用图走一遍？

---

*（本期探索记录：2026-08-04 03:30 CST，静默时段自动产出。来源：上游 issue #77921 核查 + 本地 `agent_runtime_helpers.py` 源码阅读。）*
