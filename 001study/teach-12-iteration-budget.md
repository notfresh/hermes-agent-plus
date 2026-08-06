# Teach #12：iteration budget —— agent 循环的"体力值"（从 Issue #77305 讲起）

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/77305
> 关联产出：issue 扫描候选（已本地验证代码证据）

---

## 第一层：直觉 —— 这玩意是干嘛的？

玩过 RPG 吗？角色放技能要消耗 MP（法力值），MP 空了就只能平砍。

agent 的迭代预算（iteration budget）就是 agent 的 MP：每轮"思考 → 调工具 → 拿结果"的循环要花 1 点，花完了 agent 就必须收工回家。

等等，你可能要问：**为什么 agent 需要限制自己干活的次数？** 它不是越努力越好吗？

因为 agent 是个大语言模型驱动的循环——每转一圈都要调用一次付费 API。如果没有上限，一个 bug 可能导致它原地打转几小时、烧掉你一个月的 API 预算。所以 Hermes 给每个 agent 发了一张"餐券本"：**总共 90 张（父 agent），子代理 50 张（可配置）**，用完了强制停。

但这里藏着一个设计细节：**什么时候撕餐券？** 是进餐厅前撕，还是吃完再撕？

> 🤔 思考题：如果你是设计师，你会选择"先撕券再吃饭"还是"吃完再撕券"？各有什么好处？

---

## 第二层：动手 —— 手走一遍"撕券"流程

我们来看 agent 核心循环 `agent/conversation_loop.py` 的真实结构（本地 fork 版本，行号与 upstream 略有差异但逻辑一致）：

```python
# conversation_loop.py:715 —— 循环的"闸门"
while (api_call_count < agent.max_iterations
       and agent.iteration_budget.remaining > 0) \
      or agent._budget_grace_call:
    # ... 组装请求参数 ...

    api_call_count += 1              # ← 第 727 行：先记账
    agent._api_call_count = api_call_count

    if agent._budget_grace_call:
        agent._budget_grace_call = False   # 用掉"宽限票"
    elif not agent.iteration_budget.consume():   # ← 第 736 行：先撕券
        _turn_exit_reason = "budget_exhausted"
        break                          # 券没了，强制退出

    # ... 真正调用模型 API（可能失败！）...
    response = agent._perform_api_call(...)
```

手走一遍正常流程（假设预算 3）：

| 轮次 | 撕券前剩余 | consume() 后 | API 调用 | 结果 |
|---|---|---|---|---|
| 1 | 3 | 2 | 成功 | 继续 |
| 2 | 2 | 1 | 成功 | 继续 |
| 3 | 1 | 0 | 成功 | 收工 |

一切正常。现在模拟 Issue #77305 的场景——**API 调用失败（HTTP 429 限流）**：

| 轮次 | 剩余 | consume() 后 | API 调用 | 结果 |
|---|---|---|---|---|
| 1 | 3 | 2 | 🔴 429 | fallback 链启动，换备用模型 |
| 2 | 2 | 1 | 🔴 429 | 再换 |
| 3 | 1 | 0 | 🔴 429 | **券耗尽，强制退出** |

看出问题了吗？**三次失败的尝试和三次成功的尝试，扣的券一样多。** 子代理明明还有备用模型没试完，却被"饿死"在限流里了。

> 🤔 思考题：上面这个模拟里，如果第 3 次 429 后 fallback 模型其实能成功，agent 还能继续吗？为什么？

---

## 第三层：为什么 —— 先撕券 vs 事后退款

现在到了最精彩的部分：**这个设计不是失误，而是一个刻意（但漏了一半）的安全机制。**

**为什么要在调用前撕券（而不是事后）？**

想象一下如果改成"调用成功才扣券"：agent 每次调用前都不扣，失败就重试、再失败再重试……如果 fallback 链有 3 个模型、每个重试 3 次，一次"逻辑回合"可能烧掉 9 次真实 API 调用却不消耗任何预算。一个失控的循环（比如 prompt 里有指令让模型不断调用工具）就会变成**无限烧钱机器**——这正是预算机制要防的东西。

所以"先撕券"是**安全阀**：宁可多扣，不可失控。

**那为什么又要有 `refund()`（退款）？**

因为有些调用**不该算数**。看 `agent/iteration_budget.py`：

```python
def consume(self) -> bool:
    """Try to consume one iteration.  Returns True if allowed."""
    with self._lock:
        if self._used >= self.max_total:
            return False
        self._used += 1
        return True

def refund(self) -> None:
    """Give back one iteration (e.g. for execute_code turns)."""
    with self._lock:
        if self._used > 0:
            self._used -= 1
```

注意 docstring 里的 `(e.g. for execute_code turns)`——**设计者早就知道"有些回合不该扣券"**。`execute_code`（程序化工具调用）不消耗模型推理，所以用完就 refund。

于是 Issue #77305 的本质浮出水面：**execute_code 有退款，API 失败没有退款。** 失败后的 fallback 尝试是"同一个逻辑回合的补救"，不是"新的一轮思考"——却按新回合扣了券。这是"安全阀"与"公平性"之间缺失的那半边。

> 🤔 思考题：如果简单粗暴地"失败就全额退款"，会引入什么新问题？（提示：想想 agent 陷入死循环重试的场景）

---

## 第四层：细节 —— 修复的三种思路

Reporter 在 #77305 里给了三个方向的方案，我们来拆解各自的权衡：

**方案 A：失败时 refund() 一次**
```python
try:
    response = agent._perform_api_call(...)
except RetryableAPIError:
    agent.iteration_budget.refund()   # 把刚撕的券还回去
    raise
```
- 优点：改动最小（几行），直接复用现有 `refund()`
- 缺点：如果 `try_activate_fallback` 内部本身有 3 次重试，每次失败都 refund，一个回合可能"免费"重试 N 次——安全阀被削弱

**方案 B：fallback/重试不计入回合预算，单独设恢复次数上限**
- 优点：最稳健——预算只管"真正的思考回合"，恢复尝试有独立的 cap（比如每回合最多试 2 个 fallback）
- 缺点：改动面大，要动 `conversation_loop` 的计数逻辑和 `try_activate_fallback` 的调用契约

**方案 C（测试先行）：** 写一个子代理测试——主 provider 每次都 429，备用 provider 健康，断言子代理能完成任务而不是死于 `max_iterations`。不管选 A 还是 B，这个测试都是验收标准。

我的判断：**B 最正确，A 可以作为过渡**。而且注意 reporter 的实测数据——10 个红队子代理里 6 个死在 58-90 次工具调用后的 429 上，说明这不是理论问题，是真实事故。

**坑提醒**：改这个要小心 `conversation_loop.py` 里 `_budget_grace_call`（宽限票）机制——它和 budget 是两个独立的闸门，改动时别把两者的语义搞混。

> 🤔 思考题：为什么说"先写测试再选方案"是对的？（提示：方案 A 和 B 都能让那个测试变绿，但代价不同）

---

## 第五层：关联 —— 跟别的模块有什么联系？

还记得我们前面学过的东西吗？这个 issue 其实串起了好几条线：

1. **tools/delegate_tool.py** —— 子代理的 50 次预算从这里来（`delegation.max_iterations`）。"父代理 90 + 每个子代理 50"意味着总消耗可以超过父代理上限——预算系统是**分层的**，不是全局一个计数器。
2. **execute_code 的 refund 先例** —— "哪些调用算回合、哪些不算"这个分类问题，在工具层面已经解决过一次（execute_code 不算），API 失败层只是忘了照做。这就是"设计模式已存在、应用不全"的典型 bug 形态。
3. **`max_iterations` 与 `IterationBudget` 双轨制** —— 循环条件里两个闸门是 AND 关系，任何一个耗尽都停。这其实是个冗余设计（防御性编程）：一个防"显式次数上限"，一个防"配置改小后的剩余额度"。
4. **fallback 链**（`try_activate_fallback` → `_fallback_chain`）—— 我们学 agent 核心循环时讲过 provider 路由，这次是它的"饿死"场景：机制本身是好的，但外层预算没给它留活路。

**这告诉我们一个通用模式**：任何"重试/降级"机制都要问一句——**重试的成本由谁买单？** 如果重试吃掉和正常执行一样的配额，那降级机制在高压力下（正是最需要它的时候）反而最先失效。这是系统设计里的经典陷阱：**紧急机制在紧急时刻失灵**。

> 🤔 思考题：Hermes 里还有没有别的"重试/降级"路径存在同样问题？（提示：思考 provider 切换、context 压缩、memory 同步这些失败时会发生什么）

---

## 收尾

这个 issue 的价值在于：它用一次真实事故，把 agent 核心循环里"预算机制 = 安全阀"的设计哲学完整地展示了一遍，还留了一个可以动手修的真实 bug（修复点明确、本地可验证）。

**接下来你想学什么？**
- ① 深入看 `try_activate_fallback` 的 fallback 链实现（provider 路由的完整逻辑）
- ② 深入看 `delegate_tool.py` 子代理如何继承父代理的 fallback 配置（第 1463 行那条线）
- ③ 如果你对 #77305 感兴趣，我可以出一份完整的修复方案（含测试设计）供你审阅

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/77305
