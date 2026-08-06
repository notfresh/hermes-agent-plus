#!/usr/bin/env python3
"""Task001 tick20: 更新状态文件"""
import json, datetime

P = "/root/projects/hermes-agent-plus/001study/task001-state.json"
with open(P, encoding="utf-8") as f:
    st = json.load(f)

st["tick_count"] = 20
st["last_tick_time"] = "2026-08-03T12:15:00+08:00"

# 报告清单追加
if "teach-12-iteration-budget.md" not in st["reports_generated"]:
    st["reports_generated"].append("teach-12-iteration-budget.md")

# 更新旧条目状态
for it in st["issues_identified"]:
    if it["number"] == 77211:
        it["status"] = "🔴 已撞车 — 08-03T12:05Z 复查：PR #77231 (open, fix(update): check Node.js deps health on already-current ch) 已引用，AI triage 评论也指向它。方案与本地设想（_node_modules_healthy）一致。弃用。"
        it["notes"] = "撞车速度验证：创建 08-03T01:15Z，PR #77231 当天出现。候选质量判断（修复点明确+有镜像模式）正确，只是来不及。"
    elif it["number"] == 77173:
        it["status"] = "🟡 风险升高 — 08-03T12:05Z 复查：仍无 cross-ref，但 reporter @szzhoujiarui 亲自评论'我本地复现了 directory 和 oversized binary 的 false positives，认为应分离处理'——reporter 正自己推进，极可能很快提 PR。暂不推荐，继续观望。"
    elif it["number"] == 75416:
        it["status"] = "🟡 仍干净 — 08-03T12:05Z 复查未做（配额优先给新候选），保持上次结论：修复点模糊，吸引力低。仅记录。"

# 新增条目（今天的扫描）
new_issues = [
    {
        "number": 77305,
        "title": "fix(delegation): failed API calls consume the subagent iteration budget, starving the fallback chain（API 调用失败也扣迭代预算，fallback 链被饿死）",
        "labels": "（无标签）",
        "difficulty": "★★☆ 中等（修复点明确，方案需权衡安全阀 vs 公平性）",
        "status": "🟢 干净 — 08-03T03:44Z 创建，12:05Z 核查：无 assignee/评论/cross-ref。本地已验证代码证据：conversation_loop.py:727 api_call_count+=1 与 :736 iteration_budget.consume() 均在 API 调用前执行，失败路径无 refund；iteration_budget.py:45 refund() 存在但仅 execute_code 用。reporter 给出行号+实测数据（10 子代理 6 个死于 429 后 max_iterations）。",
        "fix_point": "agent/conversation_loop.py:727/736（失败路径不 refund）；iteration_budget.py:45 refund() 已有先例（execute_code）",
        "fix_idea": "方案A：RetryableAPIError 时 refund()（改动最小）；方案B：fallback/重试不计入回合预算、单独 cap 恢复次数（最稳健）；验收测试：主 provider 全 429 + 备用 provider 健康 → 子代理须完成任务而非死于 max_iterations",
        "notes": "✅ 推荐！直接命中用户学习重心（agent 核心循环/预算机制/fallback 链），教学产出 teach-12-iteration-budget.md 已写。撞车风险：创建仅 ~1h，reporter 可能自己提 PR（参照 #77256 模式），下次 tick 先复查。"
    },
    {
        "number": 77256,
        "title": "[Bug]: try_activate_fallback misses api.kimi.com/coding anthropic_messages endpoint（fallback 检测漏掉 Kimi coding 的 anthropic_messages 模式）",
        "labels": "type/bug, comp/agent, provider/kimi, P2",
        "difficulty": "★☆☆~★★☆",
        "status": "🔴 已撞车 — 08-03T12:10Z 核查：PR #77304 (RelaxJonh 自提) + PR #77308 两个 PR 同时引用。弃用。",
        "fix_point": "try_activate_fallback 的 fb_api_mode 推导启发式",
        "fix_idea": "弃用",
        "notes": "撞车速度验证 2：issue 创建 03:45Z，PR 当天即出，还出俩。"
    },
    {
        "number": 77284,
        "title": "custom_providers: add bearer_auth option for Anthropic-compatible endpoints",
        "labels": "type/feature, comp/agent, provider/anthropic, area/auth, area/config, P3, needs-decision",
        "difficulty": "★★☆（feature + needs-decision，方向未定）",
        "status": "🟢 干净 — 08-03T03:29Z 创建，12:10Z 核查：无 assignee/评论/cross-ref。",
        "fix_point": "custom_providers 配置解析（provider 认证机制）",
        "fix_idea": "待读代码定位；needs-decision 意味着维护者未定方向，撞车/被关风险高",
        "notes": "备选。与 provider 连接机制相关（agent 基础机制），但 needs-decision + feature 类，吸引力中等。"
    },
    {
        "number": 77264,
        "title": "[Feature]: Curator consolidation should include archived skills — auto-review of archived skills before pruning",
        "labels": "type/feature, comp/agent, comp/cron, tool/skills, P3, needs-decision",
        "difficulty": "★★☆（curator 生命周期逻辑）",
        "status": "🟢 干净 — 08-03T03:08Z 创建，12:10Z 核查：无 assignee/评论/cross-ref。",
        "fix_point": "agent/curator.py 的 consolidation 逻辑",
        "fix_idea": "把 archived skills 纳入 consolidation 候选；needs-decision",
        "notes": "备选。curator 是 skill 生命周期维护层，偏离'初级核心原理'（skill 加载机制才是核心），低优先。"
    },
]
st["issues_identified"].extend(new_issues)

# awaiting_answer + 提问
st["awaiting_answer"] = True
st["last_question"] = (
    "（12:15 提问）本期扫描结果：① 复查 #77211 → 已撞车（PR #77231，方案与我们设想一致，验证了判断力但没赶上）；"
    "#77173 → reporter 本人正在跟进（'我本地复现了……'），风险升高不推。② 新候选池：今天 3 个与 agent 核心机制相关的 issue 中，"
    "#77256 已撞车（双 PR），#77284/#77264 是 needs-decision 的 feature。③ **强烈推荐 #77305**：API 调用失败也扣迭代预算、fallback 链被饿死——"
    "直接命中 agent 核心循环（iteration budget 机制），reporter 给了精确行号，我已在本地 fork 验证代码证据完全属实"
    "（conversation_loop.py:727/736 先扣费后调用、失败不退款；iteration_budget.py:45 的 refund() 只有 execute_code 在用），"
    "并写好了教学产出 teach-12-iteration-budget.md。请问：你对 #77305 感兴趣吗？"
    "选项：① 感兴趣 → 我出完整修复方案（含测试设计）供你审阅；② 只当教学素材 → 我继续深入 fallback 链教学；③ 不感兴趣 → 我继续扫新池。"
)

with open(P, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False, indent=2)
print("状态已更新: tick_count=20, issues=", len(st["issues_identified"]), ", awaiting_answer=True")
