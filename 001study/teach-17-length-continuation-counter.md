# teach-17：两个计数器，一个复位一个不复位 —— length-continuation 不对称 bug 拆解

> 教学读代码序列 · 衍生案例（非走读卡，walkthrough-3 的延伸）· 2026-08-05
> 素材来源：upstream issue #79100（已被 PR #79153 秒抢，1 行修复）
> 涉及文件：`agent/conversation_loop.py`（5780 行，agent 核心循环本体）

---

## 一、直觉：这就像"电梯超载报警器"的计数逻辑

想象电梯有个报警器：**连续**超载 4 次就锁死电梯，请维修工来。但每次超载之间如果有人下电梯（恢复正常），计数器就该归零——否则三天里每次超载一次、加起来凑够 4 次，电梯就莫名其妙锁死了，明明每次都正常恢复了。

Hermes 的 `length_continue_retries` 就是这样一个计数器，而 #79100 就是那个"凑够 4 次被锁死"的 bug。

**场景还原**：模型回复被截断（finish_reason=length），Hermes 会追加一句"继续"，最多 4 次。如果中途模型成功调用了工具（说明这轮其实活了），计数器却不归零——下次再截断，它从上次的数字继续累加。四次**不连续**的截断，第四次直接判死刑：

```
Response remained truncated after 4 continuation attempts
```

---

## 二、动手：三个复位点 vs 一个缺失的复位点

先把 `length_continue_retries` 的**全部生命周期**找出来（grep 结果）：

```
conversation_loop.py:683     length_continue_retries = 0    ← 回合开始初始化
conversation_loop.py:2027    length_continue_retries += 1   ← 截断一次，+1
conversation_loop.py:2033    if length_continue_retries < 4 ← 未满 4 次就续写
conversation_loop.py:2011    length_continue_retries = 0    ← 复位点①：仅"内容过滤→切换 fallback"路径
conversation_loop.py:5480    length_continue_retries = 0    ← 复位点②：仅"回合以最终回复收尾"路径
conversation_loop.py:5083    truncated_tool_call_retries = 0 ← 兄弟计数器在这复位，它没有！
```

关键在 **5080-5083** 这段，注释明明白白写着"重置**每回合**的重试计数器"，却只重置了一个：

```python
# conversation_loop.py:5080-5083
# Reset per-turn retry counters after successful tool
# execution so a single truncation doesn't poison the
# entire conversation.
truncated_tool_call_retries = 0        # ← 只有它！length_continue_retries 漏了
```

**动手实验**（本地就能验证）：

```bash
cd /root/projects/hermes-agent-plus
# 1. 确认两个计数器初始化位置相邻
grep -n "length_continue_retries\|truncated_tool_call_retries" agent/conversation_loop.py
# 2. 看 683-684 行的初始化
sed -n '680,690p' agent/conversation_loop.py
# 3. 对比 5080 行附近：注释说 counters（复数），代码只 reset 一个
sed -n '5078,5084p' agent/conversation_loop.py
```

---

## 三、为什么：计数器要回答的永远是"最近这一次"的问题

设计意图（issue 引用的 commit `24282dce` 说得清楚）：`length_continue_retries` 应该计数的是一次**截断事件**（episode）——从截断发生到恢复为止。恢复 = 模型给出了完整回复，**或者**给出了工具调用（工具调用说明上下文没坏，这轮对话活着）。

问题出在"恢复"的两种形态没有对称处理：

| 恢复形态 | 复位点 | 存在？ |
|---------|--------|--------|
| 内容过滤后切 fallback | 2011 | ✅ |
| 回合以最终回复收尾 | 5480 | ✅ |
| **工具调用成功**（回合继续） | 5083 只复位兄弟计数器 | ❌ **缺失** |

没有这个复位点，计数器就从"单次截断事件"漂移成了"整个回合的截断次数"。四次各自独立、都能恢复的截断，被错误地叠加成一次"连续失败"。

**有和没有的差别**：没有它，长会话（很多轮工具调用）里模型偶尔截断两次就会让回合莫名暴毙；有它，每次工具调用成功都意味着"此前的截断已无关紧要，重新计数"。

---

## 四、细节：为什么 bug 藏了这么久才被发现

几个值得品的技术点：

1. **注释与代码的背离**：5080 行注释写 "per-turn retry **counters**"（复数），下面只复位了一个。读代码的人看注释以为两个都复位了——注释撒谎比代码撒谎更隐蔽，因为 grep 和 review 都信注释。
2. **复位点分散在三个条件分支**，不是集中在一个 `_reset_retry_counters()` 函数里。分散 = 容易漏。这也是为什么修法（PR #79153）不是"把复位逻辑抽成函数"而只是补一行：改动最小，风险最小。
3. **触发条件苛刻**：需要"截断 → 续写 → 工具调用 → 再截断"的交替序列，且累计 4 次。单测通常只测"连续 4 次截断"（应该锁死），没人测"截断-恢复-截断-恢复"的交替序列（应该放行）——这就是 issue 里 samrusani 说的要补的 "loop-level regression for separated truncation episodes"。
4. **兄弟计数器（truncated_tool_call_retries）的复位位置不是巧合**：5083 就在工具执行成功的代码路径上，是"本回合平安"的自然锚点。length 计数器漏挂在这个锚点上，是典型的"复制粘贴对称代码时少改了一处"。

---

## 五、关联：这是你学过的机制家族的又一员

- **teach-12（iteration budget）**：预算类机制的共同主题——"什么算消耗、什么算恢复"。budget 有 refund()（execute_code 白嫖不算），length 计数器有复位点。所有计数器都要回答：**谁负责把它拨回零？**
- **walkthrough-3（核心循环）**：5080-5099 这段就在你走读卡 3 里精读的主循环内——工具执行成功的分支。你当时看的是"工具结果回填→下一轮迭代"，现在知道这个锚点还兼职"计数器复位岗"。
- **#78245（lifecycle_guard 正则误杀）**：同样是"一处小不对称"引发的 bug 族。这类 bug 的共同特征：**对称性破坏**——两个本该同步更新的地方，一处改了另一处没改。

**思考题**：
1. **复述**：`length_continue_retries` 的三个复位点分别在什么条件下触发？缺的那个应该在哪个锚点？
2. **预测**：PR #79153 只加了 `length_continue_retries = 0` 一行。你觉得它会不会顺带把"复位逻辑抽成函数"？为什么只加一行更可能被合并？
3. **追问**：`truncated_tool_call_retries` 和 `length_continue_retries` 都限 4 次，但前者复位点多、后者少。如果让你重新设计，你会把计数器复位收敛成什么结构？（提示：想想 `_tc_boost` 在 2113 行 `2 ** truncated_tool_call_retries` 的指数退避——复位点还影响重试的"力度"）

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/79100
（撞车 PR：#79153，RelaxJonh，1 文件 1 行插入——issue 创建 05:31Z，PR 06:52Z 出现，1 小时 21 分被秒抢）
