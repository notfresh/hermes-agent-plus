# Teach 14：搬家通知——/resume 与 /branch 漏掉的 context engine 生命周期钩子

> 关联上游 issue：#77538（CLI /resume and /branch skip external context-engine session lifecycle）
> 关联 PR：#77539（fix(cli): notify context engines on resume and branch，已合并）
> 关联模块：`hermes_cli/cli_commands_mixin.py`、`run_agent.py::_transition_context_engine_session`
> 前置知识：teach-7（skills/memory）、teach-12（迭代预算）

---

## 第一层：直觉——搬家的时候，你会通知谁？

想象你从旧公寓搬到新公寓。一个正常的搬家流程至少有三步：

1. **通知旧房东**：我要退租了，这是房间钥匙和这几个月的水电记录
2. **自己收拾**：清空旧房间的私人物品，把计数器归零
3. **通知新房东**：我入住啦，这是我的身份信息，以后水电费记我头上

现在假设你是**月租型酒店**的常客（agent 长期跑在同一台机器上），酒店经理（context engine）靠一个"房态表"跟踪每个房间住的是谁、住多久了。如果你换房间时**只做了第 2 步**（自己把东西搬过去），没通知经理——经理的房态表还写着"旧房间住着老张"——那么：

- 新房间的水电费记到旧房间名下（数据写错地方）
- 经理以为旧房间还有人住，不清理（状态泄漏）
- 经理的新房间入住统计永远是零（新会话没被"激活"）

Hermes 的 `/resume`（切回旧会话）和 `/branch`（从当前会话分叉新会话）就犯了第 2 步的毛病：**只做了自己这边的重置，没走完"通知旧房东 → 通知新房东"的完整流程**——至少对"外部 context engine"（插件式的上下文/压缩引擎）来说是这样。内建压缩器不受影响，所以 bug 藏了很久没人发现。

> 🤔 **思考题**：一个系统里有"内建"和"插件"两套实现，为什么插件容易踩到内建实现永远踩不到的坑？想一想"内建实现可以悄悄共享内部状态"这件事。

---

## 第二层：动手——跟着 /resume 走一遍代码

在 CLI 里输入 `/resume <session_id>`，Hermes 会切到目标会话。关键代码在 `hermes_cli/cli_commands_mixin.py` 的 `_handle_resume_command`（简化版）：

```python
# ① 记下旧会话
old_session_id = self.session_id
...
# ② 切到目标会话
self.session_id = target_id
...
# ③ 重新加载目标会话的历史消息
restored = self._session_db.get_messages_as_conversation(
    target_id, repair_alternation=True
)
self.conversation_history = restored
...
# ④ 同步 agent（bug 在这里！）
if self.agent:
    self.agent.session_id = target_id
    self.agent.reset_session_state()   # ← 无参调用！
```

第 ④ 步的 `reset_session_state()` 是"重置会话状态"的入口。但看它的签名（`run_agent.py`）：

```python
def reset_session_state(
    self,
    previous_messages: Optional[list] = None,
    old_session_id: Optional[str] = None,
    carry_over_context: bool = False,
):
    # 清 token 计数器、API 调用数、成本估算……
    # 然后：
    self._transition_context_engine_session(
        old_session_id=old_session_id,
        new_session_id=getattr(self, "session_id", None),
        previous_messages=previous_messages,
        carry_over_context=carry_over_context,
        reset_engine=True,
    )
```

`/resume` 调用时**三个参数全没传**（都是 None）——于是 `_transition_context_engine_session` 里的"完整过渡"逻辑全部哑火。我们马上看它怎么哑火的。

> 🤔 **思考题**：`reset_session_state()` 同时被 `/new`（新开会话）、`/resume`、`/branch` 三个命令调用。如果直接给 `reset_session_state` 加参数，会不会影响 `/new`？设计上怎么保证老调用方不受影响？

---

## 第三层：为什么——"半套重置"到底漏了什么？

`_transition_context_engine_session` 是给 context engine 发"生命周期事件"的枢纽。它支持三个钩子：

| 钩子 | 语义 | 什么时候该触发 |
|---|---|---|
| `on_session_end(old_id, messages)` | "旧会话结束了，这是它最后的聊天记录" | 离开旧会话时 |
| `on_session_reset()` | "计数器清零" | 任何会话切换时 |
| `on_session_start(new_id, **ctx)` | "新会话开始了，这是它的背景信息" | 进入新会话时 |

看它怎么决定触发哪些钩子（`run_agent.py`，upstream 版本）：

```python
if old_session_id and previous_messages is not None and hasattr(engine, "on_session_end"):
    engine.on_session_end(old_session_id, previous_messages)

if reset_engine and hasattr(engine, "on_session_reset"):
    engine.on_session_reset()

should_start = bool(
    old_session_id
    or previous_messages is not None
    or carry_over_context
    or extra_context
)
target_session_id = new_session_id or getattr(self, "session_id", "") or ""
if should_start and target_session_id and hasattr(engine, "on_session_start"):
    engine.on_session_start(target_session_id, **start_context)
```

重点看 `should_start` 的计算：**它要求至少一个上下文参数非空，才发 `on_session_start`**。

`/resume` 无参调用 → `old_session_id=None`、`previous_messages=None`、`carry_over_context=False` → `should_start=False` → `on_session_start` **永远不触发**。同理 `on_session_end` 也要求 `old_session_id` 和 `previous_messages` 都非空，同样哑火。最后只剩一个孤零零的 `on_session_reset()`。

结果：外部 context engine 收到了"清零"却没收到"退租/入住"——它的内部绑定（`_session_id`、旧会话的索引状态）**还指着旧会话**。新会话的写入会落到错误的地方，旧会话的状态永远不清理。这就是 issue 标题说的 "skip external context-engine session lifecycle"。

**为什么内建压缩器没事？** 因为它还有一个兜底：`reset_session_state` 尾部会检查 `engine.bind_session_state(...)`，当 `target_session_id != engine._session_id` 时重新绑定。内建引擎实现了这个私有方法，插件引擎没有（它们依赖公开的 `on_session_start` 钩子）。**两套实现，两条路径，修复只修了公开路径**——这解释了为什么这个 bug 存在很久却没被内建用户发现。

> 🤔 **思考题**：`should_start` 的布尔逻辑为什么要写成"四个条件任一为真"而不是"永远触发"？想想 `on_session_start` 的调用方有哪些，触发它有没有代价？

---

## 第四层：细节——PR #77539 怎么修的

修复极其小巧（+9 行，两处调用点），核心思路：**把"搬家信息"传进去**。

```diff
 # _handle_resume_command 里：
 old_session_id = self.session_id
+old_conversation_history = list(self.conversation_history)   # 先备份旧消息
 ...
 if self.agent:
     self.agent.session_id = target_id
-    self.agent.reset_session_state()
+    self.agent.reset_session_state(
+        previous_messages=old_conversation_history,
+        old_session_id=old_session_id,
+    )
```

`/branch` 同样：

```diff
 if self.agent:
     self.agent.session_id = new_session_id
     self.agent.session_start = now
-    self.agent.reset_session_state()
+    self.agent.reset_session_state(
+        previous_messages=list(self.conversation_history),
+        old_session_id=parent_session_id,
+    )
```

两个值得品味的细节：

1. **`list(self.conversation_history)` 的拷贝**——`previous_messages` 会传给 `on_session_end`，而之后 `self.conversation_history` 马上被替换成目标会话的消息。如果不拷贝，插件拿到的"旧消息"可能在触发时已经被改掉了（Python 里列表是引用传递）。用 `list()` 浅拷贝锁住当前内容，确保 `on_session_end` 拿到的是**离开那一刻**的对话。

2. **复用而非新造**——修复没有发明新方法，而是让现有 `reset_session_state` 的"参数非空即升级为完整过渡"机制被真正用起来。`/new` 等老调用方依旧无参调用，行为完全不变（向后兼容）；只有需要完整生命周期的调用方传参。这是典型的"扩展现有代码，而不是加新表面"（还记得 AGENTS.md 的 Footprint Ladder 吗？第一级就是 extend existing code）。

配套测试（`tests/cli/test_branch_command.py`）用一个假的 `ExternalEngine` 记录钩子调用顺序，断言必须是 `end → reset → start`，且 `start` 里带上了 `old_session_id`：

```python
assert calls[0] == ("end", old_session_id, old_history)
assert calls[1] == ("reset",)
assert calls[2][0:2] == ("start", cli_instance.session_id)
assert calls[2][2]["old_session_id"] == old_session_id
```

这个测试本身就是一份"生命周期契约"文档：**顺序**（先退租再入住）、**参数**（旧会话 id 必须传给新会话的 start 上下文）。

> 🤔 **思考题**：为什么测试要断言 `start` 的 `kwargs` 里包含 `old_session_id`？想想外部 context engine（比如"跨会话记忆"插件）拿到这个字段能做什么。

---

## 第五层：关联——这跟 memory provider 的 on_session_switch 是同一类问题

还记得 teach-7 里 memory 机制吗？`/resume` 和 `/branch` 的代码里，在 `reset_session_state()` 旁边就有一行：

```python
_mm.on_session_switch(target_id, parent_session_id=old_session_id or "",
                      reset=False, reason="resume")
```

Memory provider 有专门的 `on_session_switch` 钩子处理会话切换（issue #6672 引入），而且**传了 `parent_session_id`**——因为记忆需要知道"新会话从哪个旧会话延续而来"，才能继承或隔离记忆。而 context engine 的 `on_session_start` 这次才拿到 `old_session_id`。两个子系统在各自的演进中遇到了**同一个问题**（会话切换时的状态重绑），却走了两条路：memory 有专用钩子，context engine 用通用生命周期钩子。这正是读源码时值得留意的模式：**"同一类问题在不同子系统的两种解法"往往是架构演进的自然结果，不是设计失误**。

思考题（抛砖引玉）：

1. **复述**：`/resume` 之前为什么只触发 `on_session_reset` 而不触发 `on_session_end` / `on_session_start`？修复是怎么让三个钩子都触发的？
2. **预测**：如果修复时**不**拷贝 `list(self.conversation_history)`，什么场景下 `on_session_end` 会拿到错误的消息内容？（提示：`/resume` 拿到旧消息引用后，代码接下来对 `self.conversation_history` 做了什么？）
3. **追问**：`reset_session_state` 的无参调用路径现在只服务 `/new` 了。那 gateway 侧（消息平台）的 `/new`、TUI 的会话切换走的是同一条路吗？如果它们是**另一条**切换路径，是不是也存在同样的"半套生命周期"隐患？（提示：搜 `reset_session_state(` 的所有调用点，看看哪些传参、哪些没传。）

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/77538 ｜ 修复 PR：#77539

## 接下来你想学什么？
- 想不想看 gateway（消息平台）的会话切换路径，验证思考题 3 的猜测？
- 或者换口味，看下一份走读卡（skill frontmatter 解析 + `_skill_should_show()`）？
- 也可以挑一个你好奇的模块，我来带你走。
