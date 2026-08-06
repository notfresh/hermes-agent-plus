# Teach 15：门卫名单漏了一条——压缩"完成通知"绕过 progress_notices 开关

> 关联上游 issue：#77549（compaction completion notice ignores progress_notices=false）
> 关联 PR：#77551（fix(gateway): gate compaction completion notice，已合并）
> 关联模块：`gateway/run.py::_prepare_gateway_status_message`、`agent/conversation_compression.py`
> 前置知识：teach-6（gateway）、teach-13（消息体检）

---

## 第一层：直觉——夜店的"熟客名单"漏了一个人

想象你是夜店门卫。店里有条规定：**有些客人是"吵杂名单"**——比如喝高了的、到处嚷嚷的，一律不让进，除非他们手里有老板签的 VIP 通行证。

你的工作流程是：

1. 客人来了，先查"吵杂名单"（一个正则）——**在名单上吗？**
   - 不在名单上 → 直接放行 ✅
   - 在名单上 → 查第二步
2. 在名单上，但有 VIP 通行证（`progress_notices: true` 且属于"压缩进度"）→ 放行
3. 在名单上且没通行证 → 拦下 ❌

这个制度本来运行得很好。直到有一天，一位**看起来文质彬彬的客人**来了——"✓ Context compaction complete"（压缩完成通知）——他不在吵杂名单上，于是门卫直接放行了。可是等等，他是压缩状态消息啊！压缩**开始**的消息在名单上（被拦），压缩**完成**的消息却大摇大摆走进去了？

这就是 issue #77549：**压缩完成通知绕过了 `progress_notices` 开关**。用户明明没开"压缩进度通知"（默认关），却还是能在聊天里看到压缩完成的提示；而压缩开始的提示却被正常拦住了——**不对称**。

> 🤔 **思考题**：为什么"完成通知"会不在名单上？想想写名单的人（维护者）当时是怎么把"开始通知"加进去的——"完成通知"和"开始通知"是同一个时刻、同一次提交加的吗？

---

## 第二层：动手——把两条消息分别过一遍门卫

压缩发生时，agent 会发出两个状态消息（`agent/conversation_compression.py` 里的常量）：

```python
COMPACTION_STATUS = "🗜️ Compacting context — summarizing earlier conversation so I can continue..."
COMPACTION_DONE_STATUS = "✓ Context compaction complete — continuing turn..."
```

这两个消息都会进入 `gateway/run.py::_prepare_gateway_status_message()`——所有 agent 状态回调在发给聊天平台前的**唯一关卡**：

```python
def _prepare_gateway_status_message(platform, event_type, message):
    text = str(message or "").strip()
    if not text:
        return None
    if _gateway_surface_passes_raw_text(platform):
        return text                      # CLI/TUI/API 走原始通道，不拦

    text = _redact_gateway_user_facing_secrets(text)
    if _TELEGRAM_NOISY_STATUS_RE.search(text):          # ① 在吵杂名单上吗？
        # ② 有 VIP 通行证吗？（progress_notices 开启 且 属于压缩进度）
        if not (_gateway_compression_progress_notices_enabled()
                and _COMPRESSION_PROGRESS_STATUS_RE.search(text)):
            return None                  # 拦下
    return text                          # 放行
```

**修复前**，把两条消息分别过一遍（默认配置 `progress_notices=false`）：

| 消息 | 匹配 `_TELEGRAM_NOISY_STATUS_RE`？ | 结果 |
|---|---|---|
| 🗜️ Compacting context — summarizing... | ✅ 名单里有 `compacting\s+context...` 这条 | 进入 ② → 没通行证 → **拦下** ✅ |
| ✓ Context compaction complete — continuing... | ❌ 名单里**没有**这条 | 直接放行 → **漏网** ❌ |

**修复后**（PR #77551），名单里加了一条、VIP 名单里也加了一条，两条消息行为完全对称：

| 消息 | progress_notices=false | progress_notices=true |
|---|---|---|
| 开始通知 | 拦下 | 放行（在 VIP 名单里） |
| 完成通知 | **拦下**（修复后） | 放行（修复后） |

> 🤔 **思考题**：修复前"完成通知"能正常到达聊天，说明它**没匹配**噪声正则。那你觉得修复方式是"把它加进噪声正则"这么简单吗？加进去之后会不会有副作用？（提示：想想谁还读这个正则。）

---

## 第三层：为什么——"名单"为什么要用模板自动生成？

现在到揭秘环节。注意上面表格里有个反常现象：**"完成通知"没在吵杂名单里，是 bug；但"开始通知"在名单里，也是靠一行行手写正则**：

```python
_TELEGRAM_NOISY_STATUS_RE = re.compile(
    r"(auxiliary\s+.+\s+failed"
    r"|compression\s+summary\s+failed"
    r"|compacting\s+context\s+[—-]\s+summarizing\s+earlier\s+conversation"  # ← 手写的开始通知
    ...
```

问题来了：状态文案是**常量**（在 `conversation_compression.py` 里），名单是**手写正则**。它们俩是两份独立维护的东西——文案改一个字，正则就失配；新加一个状态常量，没人记得更新正则。这就是经典的 **"常量与正则漂移"** 问题（upstream 注释里点名的 #69550 教训）。

所以维护者后来引入了一个聪明的小工具 `_status_template_to_regex`：**从常量模板自动生成正则**，让"名单"跟着"文案"走，永不失配：

```python
def _status_template_to_regex(template: str) -> str:
    """把 'Compacting context — summarizing...' 变成能匹配任意数字的正则。"""
    parts = re.split(r"\{[^{}]*\}", template)   # 按 {占位符} 切段
    return r"[\d,]+".join(re.escape(part) for part in parts)
    # 例："{n} messages" → "messages" 前插 [\d,]+ → r"[\d,]+ messages"
```

然后用它批量生成"压缩进度 VIP 名单"：

```python
_COMPRESSION_PROGRESS_STATUS_RE = re.compile(
    "|".join(_status_template_to_regex(t) for t in (
        COMPACTION_STATUS,
        PRE_API_COMPRESSION_STATUS_TEMPLATE,
        PREFLIGHT_COMPRESSION_STATUS_TEMPLATE,
        IDLE_COMPACTION_STATUS_TEMPLATE,
        ...
    )),
    re.IGNORECASE,
)
```

**为什么这个设计是对的方向？** 它把"哪些状态是压缩进度"这个**语义判断**集中在一处（模板列表），而不是散落在手写正则里。以后压缩状态再变，只改常量，VIP 名单自动跟着变。**但**——注意：`COMPACTION_DONE_STATUS` 是后来才加的常量（完成通知是 #69546 加的新特性），加的时候只改了 `conversation_compression.py`，**忘了同步这两处正则**。漂移的根源不是机制不好，而是机制覆盖不全：开始通知走的是"模板自动生成"，完成通知压根不在任何模板列表里。

> 🤔 **思考题**：手写正则 vs 模板生成，各自适合什么场景？为什么"吵杂名单"（噪声正则）里既有手写也有模板生成的条目？如果全部改成模板生成，会丢掉什么能力？

---

## 第四层：细节——PR #77551 的两行半修复

修复只有两处小改动（`gateway/run.py`）：

```diff
 _TELEGRAM_NOISY_STATUS_RE = re.compile(
     r"|..."
     r"|compacting\s+context\s+[—-]\s+summarizing\s+earlier\s+conversation"
+    rf"|{re.escape(COMPACTION_DONE_STATUS)}"          # ① 吵杂名单：加完成通知
     r"|resumed\s+after\s+\d+s\s+idle\s+[—-]\s+compacting"
     ...
 )
 ...
 _COMPRESSION_PROGRESS_STATUS_RE = re.compile(
     "|".join(_status_template_to_regex(_template)
              for _template in (
                  COMPACTION_STATUS,
+                 COMPACTION_DONE_STATUS,               # ② VIP 名单：加完成通知
                  PRE_API_COMPRESSION_STATUS_TEMPLATE,
                  ...
```

两个细节值得品：

1. **`re.escape()` 的使用**——①处把完整常量文本 `re.escape` 后拼进正则。为什么不也用 `_status_template_to_regex`？因为 `COMPACTION_DONE_STATUS` 是**固定文案**（没有 `{占位符}`），模板转换对它是平凡操作；`re.escape` 更直接、意图更明确：**"这一整句话就是名单条目"**。而 ②处放进模板列表走 `_status_template_to_regex`，是为了跟其他压缩进度条目**共享同一个转换管道**——万一以后完成通知文案加了数字占位符，自动跟上。同一份修复，两处用了两种拼接方式，各自对应各自的场景。

2. **配套测试的"反转"**——这是最妙的部分。修复前测试叫 `test_compaction_completion_notice_reaches_chat`（"完成通知能到达聊天"），参数化 `enabled=[True, "default"]`，断言**两种模式都放行**——这个测试把 bug 的"漏网"行为**固化成了契约**！修复后测试改名为 `test_compaction_completion_notice_follows_progress_gate`，断言变成 `expected = COMPACTION_DONE_STATUS if enabled else None`。也就是说：**测试从"背书不对称"翻转为"强制对称"**。读 PR 时看到这种"测试断言反转"，基本就能确认作者是真懂这个 bug 的本质（不对称），而不只是补一行正则。

> 🤔 **思考题**：修复后，`progress_notices=true` 时完成通知能到达聊天，靠的是哪一处修改？如果只加 ①不加 ②，`progress_notices=true` 的用户会看到什么？如果只加 ②不加 ①呢？（提示：门控逻辑是"先查吵杂名单，再查 VIP 名单"。）

---

## 第五层：关联——这是"默认静音"设计哲学的一个切片

回看 teach-6（gateway）：消息平台是**人**在看，Hermes 对聊天通道的默认姿态是**安静**——aux 任务失败、provider 重试、压缩进度……这些"运行细节"默认不打扰用户，除非显式 opt-in。`progress_notices` 只是这个大哲学的一个开关。而这个 bug 的根因——**新状态常量加了，过滤名单没同步**——在大型代码库里几乎是必然事件：**"emit 点"和"过滤点"物理上隔了几百行、属于不同模块**，没有任何机制强制它们同步，全靠人记性。

这跟 teach-13 的"双防线"（repair + sanitize）是同一个架构问题的两面：**数据产生点（emit）与消费点（gateway）之间的契约，要么靠测试锁死，要么靠生成机制（模板→正则）消除漂移，要么迟早漂移出 bug**。Hermes 的解法是"生成机制 + 契约测试"双管齐下——模板消除文案漂移，测试锁死行为对称。

思考题（抛砖引玉）：

1. **复述**：`_prepare_gateway_status_message` 的过滤流程分几步？"吵杂名单"和"VIP 名单"分别是什么？修复前完成通知为什么能漏网？
2. **预测**：如果有人在 `conversation_compression.py` 里新加一个状态常量 `COMPACTION_RETRY_STATUS = "🔄 Compaction interrupted — retrying..."` 但忘了更新 `gateway/run.py` 的两个正则，会出现什么行为？（提示：这个文案会不会匹配 `_TELEGRAM_NOISY_STATUS_RE` 里的 `compaction` 相关条目？）
3. **追问**：`_TELEGRAM_NOISY_STATUS_RE` 里的手写条目（如 `auxiliary\s+.+\s+failed`）为什么**不能**改成模板生成？这类"跨多个 emit 点、文案不统一"的噪声，用模板怎么表示？（提示：模板生成要求每个状态有唯一常量；aux 失败可能有十几种不同文案。）

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/77549 ｜ 修复 PR：#77551

## 接下来你想学什么？
- 想不想顺着"emit 点 vs 过滤点"这条线，看看 `_emit_status` 是怎么从 agent 一路传到 gateway 的（完整状态管道）？
- 或者看下一份走读卡（skill frontmatter 解析 + `_skill_should_show()` 显示条件）？
- 也可以挑别的模块，我带你看。
