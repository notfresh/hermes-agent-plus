# Issue 10：openai-api 直连把所有模型都当推理模型，无条件发 reasoning.effort

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/76255
> 状态：🟢 干净候选（无认领、无评论、无关联 PR，2026-08-02 00:07 核查）
> 标签：暂无（未 triage）；type/bug 属性明显，P2 量级（provider 直连完全不可用）
> 版本：0.19.1 复现，upstream main（08-02 快照）仍存在

## 一句话

`model.provider: openai-api`（直连 api.openai.com）时，**每个请求都会带上 `reasoning: {effort: "medium", summary: "auto"}`**，OpenAI 对不支持该参数的非推理模型（gpt-4o-mini / gpt-4.1-mini）直接回 HTTP 400 —— 直连 OpenAI 在非推理模型上完全不可用。

## Premise 验证（本地代码实锤，比 reporter 自己 trace 得更深）

Reporter 卡在"`_supports_reasoning_extra_body()` 应该返回 False，但错误照常复现"。答案：**那条 gate 只保护 chat_completions 传输层，openai-api 根本不走那层**。

**关键发现 1**：`hermes_cli/providers.py:67` —— openai-api 的传输层是 **codex_responses**，不是 openai_chat：

```python
"openai-api": HermesOverlay(
    transport="codex_responses",          # ← 走 Responses API
    base_url_override="https://api.openai.com/v1",
    base_url_env_var="OPENAI_BASE_URL",
),
```

**关键发现 2**：`agent/transports/codex.py:172` —— 推理**默认开启**：

```python
reasoning_effort = "medium"
reasoning_enabled = True                    # 用户没关 reasoning 就默认 True
```

**关键发现 3**：`agent/transports/codex.py:304-310` —— 除 xAI / GitHub 外**无条件**发 reasoning 参数：

```python
elif reasoning_enabled:
    if is_github_responses:
        github_reasoning = params.get("github_reasoning_extra")
        if github_reasoning is not None:
            kwargs["reasoning"] = github_reasoning
    else:
        kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}   # ← 无模型判断
        kwargs["include"] = (
            ["reasoning.encrypted_content"] if replay_encrypted_reasoning else []
        )
```

对比 xAI 分支（287-303 行）已经修过同款 bug：`grok_supports_reasoning_effort(model)` 白名单校验，不在名单 → **整个 reasoning key 不发**。openai 分支缺的就是这个。

## 为什么是"应该修"

- **功能完全坏**：直连 OpenAI 是官方支持的 provider（picker 里有），配 gpt-4o-mini 这种便宜模型是常见用法，现在 100% 400。
- **修复模式现成**：照抄 xAI 分支的既有先例，风险极低。
- **本地可测**：kwargs 在 HTTP 调用前构建，纯单元测试即可，不需要 API key。

## 修复方案（★★☆ 中等，2 文件 + 1 测试，~15 行）

1. **`agent/model_metadata.py`**：仿 `grok_supports_reasoning_effort()`（385 行）加一个 OpenAI 版白名单：

```python
# OpenAI Responses API 接受 reasoning.effort 的模型前缀（o1/o3/o4/gpt-5.x）
_OPENAI_EFFORT_CAPABLE_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-5.")

def openai_supports_reasoning_effort(model: str) -> bool:
    """保守设计：不在名单就不发 effort，宁可不发也不要 400（与 grok 一致）。"""
    name = (model or "").strip().lower()
    if not name:
        return False
    return any(name.startswith(p) for p in _OPENAI_EFFORT_CAPABLE_PREFIXES)
```

2. **`agent/transports/codex.py` 304-310**：else 分支加 gate——直连 OpenAI（`provider == "openai-api"` 或 base_url 含 api.openai.com）时只在模型支持时发 reasoning；其余自定义 Responses 路由保持现状（或同样保守 gate，需 maintainer 拍板）：

```python
else:
    if params.get("provider") == "openai-api" and not openai_supports_reasoning_effort(model):
        pass  # 非推理模型：整个 reasoning key 都不发（同 xAI 先例）
    else:
        kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
        ...
```

3. **测试**：`tests/agent/transports/test_codex.py`（或既有 test_chat_completions.py 同目录）——断言 openai-api + gpt-4o-mini 时 kwargs 无 `reasoning` 键；openai-api + o4-mini 时有。

## 风险点

- 注意 `"gpt-5"` 前缀会误伤 `gpt-5.6-luna/terra/sol` 之外的**非推理** gpt-5 变体？——实际上 gpt-5.x 全系都是推理模型，无此风险；但要小心 `gpt-4o` 前缀**不能**进白名单（它拒绝 reasoning.effort）。
- 若将来 OpenAI 给 gpt-4o 系列也开放 effort，白名单加前缀即可，不用改结构。
- 测试要覆盖 `provider="openai-api"` 与 `base_url=api.openai.com` 两种判定方式，避免只认一种导致漏网。

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/76255
