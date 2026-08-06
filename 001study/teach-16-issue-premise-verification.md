# teach-16：怎么「证伪」一个 issue —— auxiliary 重试链的两次剥参

> 官方 Issue：#78273（[auxiliary temperature retry can't recover when the model also rejects max_tokens](https://github.com/NousResearch/hermes-agent/issues/78273)）
> 关联产出：teach-12（iteration budget 的 fallback 链）、teach-13（message repair 的验证纪律）

---

## 第一层：直觉 —— 先别急着认领，先问「这个 bug 现在还活着吗？」

想象你是 GitHub 上的猎人。今天早上看到一个新 issue #78273，reporter 写得**特别专业**：

- 标题直接点名 `agent/auxiliary_client.py`
- 复现步骤清清楚楚：`generate_title("hello", "world")` 就炸
- 还附了抓包级证据：两次 POST、各自的 payload、各自的 400 报错
- 连根因都定位好了：「重试处理器只剥 temperature，不剥 max_tokens」
- 连修法都建议好了：「把重试改成循环，max_tokens 翻译成 max_completion_tokens」

第一反应肯定是：**这 issue 质量太高了，赶紧认领！**

打住。做贡献这件事上，有一种最常见的翻车方式叫**「前提不成立」**（AGENTS.md 里专门写了一节 *Before you call it a bug — verify the premise*）：reporter 的复现和根因都是**基于他那个版本的代码**做的。而开源仓库的代码每天都在变——他踩的坑，main 上可能早就有人填了。

本份走读卡就是带你完整走一遍「证伪」流程：怎么在**不花一分钱 API 调用**的情况下，用本地代码 + upstream diff 证明一个 issue 已经死了。

> 🤔 **思考题（复述）**：为什么「reporter 自带完整根因」的 issue 反而更危险？——提示：他证明的是「他那个版本有这个 bug」，不是「当前 main 有这个 bug」。

---

## 第二层：动手 —— 我们是怎么一步步验证的

### 第一步：读 reporter 的复现场景

他配置 `provider: openai-direct`、`model: gpt-5`，然后 `title_generator.py` 发请求：

```python
# agent/title_generator.py:124-132（本地代码，确实如此）
response = call_llm(
    task="title_generation",
    messages=messages,
    max_tokens=500,      # ← 两个参数一起发
    temperature=0.3,     # ← gpt-5 两个都拒
    ...
)
```

他的观测：POST 1 带 `temperature=0.3 + max_tokens=500` → 400「temperature 不支持」；自动重试 POST 2 剥掉 temperature → 400「max_tokens 不支持」；然后就没有然后了，用户看到的是**第一次**的错误。

### 第二步：找到重试链的代码（sync 路径）

```python
# agent/auxiliary_client.py:7143-7195（call_llm 的 except 链，节选）
except Exception as first_err:
    if "temperature" in kwargs and _is_unsupported_temperature_error(first_err):
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("temperature", None)          # ① 剥 temperature
        try:
            return _validate_llm_response(
                client.chat.completions.create(**retry_kwargs), task)
        except Exception as retry_err:
            retry_err_str = str(retry_err)
            if not (
                _is_payment_error(retry_err) or _is_connection_error(retry_err)
                or _is_auth_error(retry_err)
                or "max_tokens" in retry_err_str          # ← 关键：剥完 temperature
                or "unsupported_parameter" in retry_err_str  # 又 400，会落下来
            ):
                raise
            first_err = retry_err
            kwargs = retry_kwargs
    # ...（中间还有一堆 fallback 链）...
    if max_tokens is not None and (
        "max_tokens" in err_str                            # ← ② 再剥 max_tokens
        or "unsupported_parameter" in err_str
        or _is_unsupported_parameter_error(first_err, "max_tokens")
        or _is_zai_param_error
    ):
        kwargs.pop("max_tokens", None)
        kwargs.pop("max_completion_tokens", None)
        try:
            return _validate_llm_response(
                client.chat.completions.create(**kwargs), task)
        ...
```

**手走一遍**（假设 max_tokens 真的在 kwargs 里）：

1. POST 1：`temperature + max_tokens` → 400（temperature 被拒）
2. `retry_kwargs.pop("temperature")` → POST 2：只剩 `max_tokens` → 400（max_tokens 被拒）
3. `"max_tokens" in retry_err_str` 成立 → 不 raise，落下来 → `first_err` 更新成 max_tokens 错误
4. 走到底部 max_tokens 分支：`"max_tokens" in err_str` 成立 → 剥掉 → POST 3 → 成功 🎉

咦？那 reporter 说的「死在 max_tokens」是怎么回事？

### 第三步：发现真正的原因 —— 版本

Reporter 的环境写的是 **Hermes Agent v0.13.0（2026.5.7）**。而我验证的本地代码（HEAD 2026-07-31）+ upstream main 已经比他新了三个月。`git diff HEAD upstream/main -- agent/auxiliary_client.py` 一看：

```diff
-            kwargs["max_tokens"] = max_tokens
+            # Use auxiliary_max_tokens_param() so models that require
+            # max_completion_tokens (GPT-5 family, Copilot) get the right
+            # parameter name instead of a hardcoded max_tokens that 400s.
+            kwargs.update(auxiliary_max_tokens_param(max_tokens, model=model))
```

reporter 建议的修法（「max_tokens 应该翻译成 max_completion_tokens」）——**upstream 已经实现了**。

> 🤔 **思考题（预测）**：还有一层更早的防线：`_build_call_kwargs` 对 OpenAI 兼容端点**根本不发 max_tokens**（#34530 的设计）。猜猜为什么「省略 max_tokens」能一次性躲开多少类 400？

---

## 第三层：为什么 —— 三层防线，每一层都是历史教训

验证过程中我数出了**三道防线**，全都是在 reporter 的 v0.13.0 之后加上的：

1. **省略（#34530）**：OpenAI 兼容端点不发 `max_tokens`，让模型自己决定输出长度。一个参数都不发，就永远不会被拒。
2. **翻译（`auxiliary_max_tokens_param`）**：对 GPT-5 家族/Copilot 这类「只认 max_completion_tokens」的模型，自动换参数名。要输出上限？给你正确的那个名字。
3. **剥参重试（retry 链）**：万一是 Anthropic wire / NVIDIA NIM 这类 max_tokens 必填的端点，真被拒了就剥掉重试。

为什么这么设计？**因为「参数兼容」这件事没有银弹**：

- 直接发 `max_tokens` → GPT-5 家族 400（要 `max_completion_tokens`）
- 直接发 `max_completion_tokens` → OpenRouter / 本地模型 400（只要 `max_tokens`）
- 什么都不发 → 某些 NIM 模型返回 **200 但 choices 是空的**（更阴险，不报错但没内容）

所以策略是：**默认不发（最安全）→ 特殊端点翻译（保功能）→ 真被拒就剥（保命）**。这是一个「allow-list-free」的反应式策略——不维护「哪个模型收哪个参数」的清单，靠错误信息动态适配。清单迟早过时，错误信息是实时的。

**对比「有和没有」**：如果只有 reporter 建议的「单层循环剥参」，你永远在追着模型厂商改参数名；有了「默认省略 + 错误驱动」，模型厂商加新怪癖时你基本无感。

> 🤔 **思考题（追问）**：设计决策里写着「默认省略 max_tokens = 用模型最大输出」。这跟 `auxiliary_max_tokens_param` 的「保输出上限」是不是矛盾？想想：什么场景下省略是对的，什么场景下必须强制带上？

---

## 第四层：细节 —— 验证的严谨性检查清单

做「证伪」不能只靠读一段代码就下结论，我补了三个检查：

**① 检查点 1：局部变量 `max_tokens` 从哪来？**
重试链里 `if max_tokens is not None` 用的是 `call_llm` 的**参数**（6919 行 `max_tokens: int = None`），不是 kwargs。title_generator 传了 500，所以判断不为 None——剥参分支会触发。（如果这里用的是 `kwargs.get("max_tokens")`，而 OpenAI 兼容端点又省略了它，就会是 None——那才是真 bug 的温床。）

**② 检查点 2：本地代码 ≠ upstream？**
本地 HEAD 是 07-31，upstream main 领先。`git diff HEAD upstream/main -- agent/auxiliary_client.py` 显示 upstream 对 `_build_call_kwargs` 又改过（引进了 `auxiliary_max_tokens_param`）。**只验证本地不够**——本地是「上一周的事实」，upstream 才是「今天的事实」。

**③ 检查点 3：跑现有测试拿新鲜证据**
```
scripts/run_tests.sh tests/agent/test_unsupported_temperature_retry.py -q
# 17 passed, 2 failed
```
2 个失败是**环境坑**：测试用了 `@pytest.mark.asyncio`，但这台机器没装 pytest-asyncio 插件（`Unknown pytest.mark.asyncio` / `async def functions are not natively supported`）。这是测试基建问题，不是剥参逻辑问题——17 个同步测试全绿，覆盖了「剥 temperature」「非 temperature 400 不重试」「max_tokens 不出现在 OpenAI 兼容端点」等关键断言。

**一个坑提醒**：这套测试断言了「max_tokens 被故意省略」（115-120 行）——如果哪天有人想「让 auxiliary 也发 max_tokens 保上限」，这个测试会立刻拦下他，逼他思考要不要同时改 `_build_call_kwargs`。这就是**行为契约测试**（AGENTS.md 强调的 invariant 风格）的价值：它锁的是「两个数据之间必须怎样相关」，而不是「某个值是多少」。

> 🤔 **思考题（预测）**：如果 upstream 某天真的按 reporter 建议把剥参重试改成「迭代循环」，你觉得哪个现有测试会先红？——提示：测试断言里有一句 `assert client.chat.completions.create.call_count == 2`。

---

## 第五层：关联 —— 把「证伪」变成肌肉记忆

这已经是我们第三次遇到「看起来能做、其实做不了」的 issue 了：

| issue | 当时的判断 | 结果 |
|---|---|---|
| #75130（skill symlink） | 修复点明确 | 4 个 PR 挂着没合——**比看起来难** |
| #77921（empty tool_calls） | 教学价值极高 | 53 分钟被秒抢——**根本轮不到我们** |
| #78273（auxiliary 剥参） | reporter 自带根因 | 版本过期——**main 上早已修好** |

三种翻车方式：**低估难度、高估速度、忽略版本**。而唯一通用的防御就是今天这套流程：

1. 读 issue 时**先看 Environment 字段**（版本信息是第一个红旗）
2. 用本地代码走一遍 reporter 声称的调用链
3. `git diff` 对比 upstream，确认你验证的是「今天的事实」
4. 跑相关测试，拿机器证据而不是推理

还记得 walkthrough-1 里我们读 `iter_skill_index_files` 时的做法吗？——**同样的方法**：不从文档猜设计，从源码里找事实。读代码不只是为了「看懂」，更是为了「验证」。

最后送你一个从 #78245 来的彩蛋：今天还有个新 issue，标题是「lifecycle_guard 的正则 `p?kill` 会匹配进单词 **skill** 里面，误杀无辜命令」——注意，`skill` 这个词里就藏着 `kill`！这个 bug 从 #77173 的「漏杀 killa 变体」修到「误杀 skill」，一个正则的两端都被打了一遍。写正则的教训：`\b` 单词边界挡不住「skill 内部的 kill」，因为 `l` 和 `k` 之间没有边界。这也是个绝佳的教学素材——但它是 cron/terminal 守卫，不在我们的推荐范围，只记录。

> 🤔 **思考题（追问）**：`\b` 是单词边界，`p?kill\b` 为什么能匹配上 "skill"？——提示：`skill` 里 `kill` 的左边是 `s`，两个都是单词字符，`\b` 只认「单词字符/非单词字符」的切换点。那正确的修法应该是什么？

---

## 接下来你想学什么？

- 走读卡 2（skill frontmatter 解析 + `_skill_should_show()`）**在等你**——walkthrough-1 的实验做了吗？把结果或卡点告诉我，明天就出第 2 份
- 或者想让我把「生命周期守卫正则的两次翻车」（#77173 → #78245）展开成一份小教材？它讲的是「安全正则的攻防」——漏杀和误杀是同一枚硬币的两面
