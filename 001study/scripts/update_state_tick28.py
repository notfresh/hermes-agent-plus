#!/usr/bin/env python3
"""Task001 tick28: 静默时段状态更新（新池扫描 + 复查 + 候选验证）"""
import json

PATH = "/root/projects/hermes-agent-plus/001study/task001-state.json"
with open(PATH, encoding="utf-8") as f:
    st = json.load(f)

st["tick_count"] = 28
st["last_tick_time"] = "2026-08-05T00:30:00+08:00"

# --- 新 issue 记录（tick27 之后创建）---
new_issues = [
    {
        "number": 78600,
        "title": "search_files tool silently returns 0 results when regex contains ?, +, |, or ( ) metacharacters",
        "labels": "（未 triage）",
        "difficulty": "★☆☆ 已本地验证根因（grep fallback 用 BRE 语义）",
        "status": "🟢 干净且已验证 — 08-04T16:03Z 创建，无 assignee/评论/cross-ref。静默时段本地深挖完成：根因 = 环境无 rg 时 fallback _search_with_grep 用 `grep -rnH`（默认 BRE），? + | ( ) 全被当字面量 → exit=1 静默 0 结果；rg 路径正常（本地复现 file? 50 条匹配）。macOS desktop 常见无 rg 场景。修复 = 1 行加 -E + ERE 语义测试。",
        "fix_point": "tools/file_operations.py _search_with_grep（2396 行 `grep -rnH` → `grep -rnHE`）",
        "fix_idea": "主修复：加 -E 使 grep fallback 与 rg 语义一致（ERE）。测试：patch _has_command('rg')→False 强制 grep 路径，断言 'file?|file|files' 等 ERE 模式正常匹配。顺带关注 --exclude-dir/--include 是 GNU 扩展、BSD grep 不支持（macOS 原生 grep 会报错而非 0 结果，与 issue 现象不符 → 用户环境应为 GNU grep 或 rg 缺失）。",
        "notes": "🎯 命中学习重心（tool 系统 + fallback 路径设计 + BRE/ERE 语义陷阱）。教学价值：_search_with_rg 与 _search_with_grep 双路径设计、exit code 语义（0/1/2）、_split_tool_diagnostics。修复点明确、本地可端到端验证。推荐！"
    },
    {
        "number": 78598,
        "title": "/steer on a tool result with non-string content produces invalid content for chat-completions providers (400 loop)",
        "labels": "（未 triage）",
        "difficulty": "★★☆ 修复点已确认（wire format 传递需设计）",
        "status": "🟢 干净且已验证 — 08-04T16:01Z 创建，无 assignee/评论/cross-ref。本地已读 apply_pending_steer_to_tool_results（agent_runtime_helpers.py:3314-3373）：3359 行非字符串 content 无条件转 Anthropic block-list（3363-3365），chat-completions provider 必 400 且历史被污染（后续调用含 fallback 全挂）。",
        "fix_point": "agent/agent_runtime_helpers.py:3359-3368（非字符串 content → block-list 转换无条件执行）",
        "fix_idea": "需要 wire format 感知：chat_completions 模式把非字符串 content 转纯字符串（str(existing_content)+marker），只有 anthropic_messages 模式才用 block-list。复杂点：需查调用方（tool_executor 各调用点）能否传 api_mode，或从 agent 状态读取。",
        "notes": "🎯 命中学习重心（消息 wire format 适配，与 teach-13 message-repair 同族）。reporter 自带根因+完整复现。修复点明确但需理解消息构造链。备选推荐。"
    },
    {
        "number": 78580,
        "title": "[Bug]: max-iteration runtime nudge is treated as human intent during context compaction",
        "labels": "（未 triage）",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车 — 创建 15:34Z，PR #78594 (fix(agent): treat max-iteration nudge as synthetic during co...) 15:55Z cross-ref，21 分钟被秒抢（triage bot 评论确认）。弃用。",
        "fix_point": "handle_max_iterations() 追加 role=user nudge（chat_completion_helpers.py:2084-2115）+ _SYNTHETIC_USER_PREFIXES 不识别该 marker（conversation_compression.py:1884-1932）+ _is_synthetic_compression_user_turn()（context_compressor.py:4164+）",
        "fix_idea": "弃用。PR 思路：提取 MAX_ITERATIONS_SUMMARY_REQUEST 共享常量 + 教 _is_synthetic_compression_user_turn() 识别。",
        "notes": "🎯 教学价值高：合成消息过滤机制（与 teach-12 iteration-budget、teach-13 message-repair 同族）。撞车速度验证 +N：reporter 自带根因（精确到行）→ 21 分钟被抢。可作教学素材（合成 role=user 消息如何污染压缩快照）。"
    },
    {
        "number": 78519,
        "title": "Bug: background_review pending write field mismatch（write_file pending 用 content 字段但审批回放要 file_content）",
        "labels": "type/bug, comp/agent, tool/skills, P2",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车 — 创建 14:12Z，PR #78537 (fix(skill_manage): normalize content->file_content in staged...) 已 cross-ref。弃用。",
        "fix_point": "skill_manager_tool.py:1402 _apply_skill_write_gate 原样透传 kwargs → :1453 apply_skill_pending 用 file_content=payload.get('file_content') 取到 None → :1570 失败",
        "fix_idea": "弃用。PR 思路：skill_manage 入参 content→file_content 规范化。",
        "notes": "🎯 skill 相关命中学习重心。教学价值：pending/审批回放机制（gate 暂存→审批→回放），参数名契约不一致的经典 bug 族（reporter 另发现 memory replace pending 同型问题）。可作教学素材。"
    },
    {
        "number": 78382,
        "title": "[P1] MOA: _moa_prepared_request leaked to native OpenAI client when agent.client is replaced (fallback/rotation)",
        "labels": "type/bug, comp/agent, provider/openai, P1",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车 — 08-05T00:0X 复查：PR #78409 (fix(moa): preserve facade across client rebuilds) 已 cross-ref。19:54Z 前已出 PR。弃用（PR 本身是配置态/运行时态脱节教学素材）。",
        "fix_point": "conversation_loop.py:2319 注入条件只查 agent.provider 标签 + run_agent.py:4170 _replace_primary_openai_client 重建 native client 不改 provider",
        "fix_idea": "弃用。PR #78409 思路：client rebuild 时保留 MoA facade。",
        "notes": "撞车速度验证：P1 + reporter 自带根因 = 必秒抢（上次 18:05 复查仍干净，本次已出 PR #78409）。教学素材：配置态与运行时态脱节。"
    }
]
existing_nums = {it["number"] for it in st["issues_identified"]}
new_issues = [ni for ni in new_issues if ni["number"] not in existing_nums]
st["issues_identified"].extend(new_issues)

# 更新既有条目
for it in st["issues_identified"]:
    if it["number"] == 75130:
        it["status"] = "🟡 用户保留关注 — 08-05T00:0X 复查：仍 open，5 评论，updated 停在 08-03T10:53Z；4 个 PR（#75225/#76249/#76294/#67748）仍全部 open 未 merge。无新动态。"
    if it["number"] == 78144:
        it["status"] = "🟢 干净 — 08-05T00:0X 复查：仍无 assignee/评论/cross-ref（updated 停在 08-04T03:27Z）。备选池保持。"
    if it["number"] == 78382:
        it["status"] = "🔴 已撞车 — 08-05T00:0X 复查：PR #78409 (fix(moa): preserve facade across client rebuilds) 已 cross-ref。弃用（PR 作教学素材）。"

st["notes"] = (
    "2026-08-05 tick 28（静默时段 00:0X）：① 新池扫描（tick27 后 69 个新 issue）："
    "**#78600 search_files 正则静默 0 结果——已本地深挖验证根因**：环境无 rg 时 fallback _search_with_grep 用 `grep -rnH`（默认 BRE），? + | ( ) 全被当字面量 → 静默 0 结果；rg 路径正常（本地复现 file? 50 条匹配正常、file|files 正常）。"
    "修复 = `grep -rnH` → `grep -rnHE` 一行 + ERE 测试。🎯 命中学习重心，强烈推荐；"
    "#78598 /steer 非字符串 content 400 循环——已确认修复点（agent_runtime_helpers.py:3359-3368 无条件 block-list 化），备选推荐；"
    "#78580 max-iteration nudge 当 human intent——21 分钟被 PR #78594 秒抢（合成消息过滤教学素材）；"
    "#78519 skill pending content/file_content 字段不匹配——PR #78537 已出（pending 门控机制教学素材）；"
    "② 复查：#78382 撞车（PR #78409 preserve facade）、#78144 仍干净、#75130 无新动态。"
    "③ 静默时段遵守：不产 walkthrough-2（用户未反馈 walkthrough-1）、不推荐不问，候选先攒状态，06:00 后汇报。"
)

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False, indent=2)
print("状态更新完成，tick_count =", st["tick_count"])
