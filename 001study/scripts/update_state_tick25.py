#!/usr/bin/env python3
"""Task001 tick25: 更新状态文件（teach-14/15 产出 + 新池扫描记录）"""
import json

path = "/root/projects/hermes-agent-plus/001study/task001-state.json"
with open(path, encoding="utf-8") as f:
    st = json.load(f)

st["tick_count"] = 25
st["reports_generated"].extend([
    "teach-14-context-engine-lifecycle.md",
    "teach-15-compaction-progress-gate.md",
])

new_issues = [
    {
        "number": 78148,
        "title": "[P1] Context compaction after tool loop leaves stale '[memory]' as response template（压缩发生在 tool loop 中途，残留 '[memory]' 字符串成为后续所有回复的默认模板）",
        "labels": "type/bug, comp/agent, P1, sweeper:risk-session-state, area/sessions, area/compression",
        "difficulty": "★★☆（tool loop + compaction 交叉场景，需理解压缩输出如何污染响应路径）",
        "status": "🔴 已撞车 — 08-04T04:30Z 核查：创建 03:21Z，PR #78175 (fix(agent): discard bare tool-call marker before fallback/pe, open) 已 cross-ref（15 分钟内）。弃用。",
        "fix_point": "压缩输出残留裸 tool-call marker（[memory]），fallback/响应路径未丢弃",
        "fix_idea": "弃用（PR 已出）。PR 修复思路：fallback 前丢弃裸 tool-call marker。",
        "notes": "再次验证：P1 + 具体复现 = 秒抢。教学价值高（tool loop 与 compaction 交叉 + 响应模板污染），可作教材素材，暂不展开。"
    },
    {
        "number": 78144,
        "title": "Gateway slash menu shows zero skills when HERMES_HOME is behind a symlink（_collect_gateway_skill_entries 用 resolve() 前缀过滤，但扫描器返回未 resolve 路径 → symlink 时全部 startswith 失败）",
        "labels": "type/bug, comp/cli, comp/gateway, tool/skills, P3",
        "difficulty": "★☆☆~★★☆（路径前缀比较的 resolve 不一致，reporter 自带根因；但需确认全链路哪些路径 resolve 哪些不 resolve）",
        "status": "🟢 干净 — 08-04T04:30Z 核查：无 assignee/评论/cross-ref（创建 03:15Z，约 1 小时）。",
        "fix_point": "hermes_cli/commands.py::_collect_gateway_skill_entries（SKILLS_DIR.resolve() 前缀 vs 未 resolve 的扫描路径）",
        "fix_idea": "统一路径基准：要么扫描器也 resolve，要么过滤端不 resolve；或改用 Path.relative_to 容错。注意与 #75130 同根（symlink 路径解析不一致），修 #75130 的 PR 可能顺带覆盖，需持续盯。",
        "notes": "🎯 直接命中用户学习重心（skill 加载机制）+ 与 #75130 同根的教学联动。当前干净，是备选池新成员。按决策 B 只记录+汇报提一句，不展开方案，等用户反馈。"
    },
]
st["issues_identified"].extend(new_issues)

st["last_tick_time"] = "2026-08-04T12:15:00+08:00"
st["notes"] = st["notes"] + " | 08-04 12:1X tick 25（用户决策 B 首 tick）：① 产出 teach-14（#77538 context-engine 生命周期 → PR #77539 修复 diff 精读：/resume /branch 传 previous_messages/old_session_id 触发完整 on_session_end→reset→start 生命周期）与 teach-15（#77549 compaction 完成通知 → PR #77551 两处修改：噪声正则+进度模板列表加 COMPACTION_DONE_STATUS，测试断言从'总放行'反转为'跟随门控'）；② 附带新池扫描：三个标签池仍 0；新 issue 119 个，命中学习重心的 2 个——#78148（P1 压缩残留 [memory]，15 分钟内被 PR #78175 秒抢，弃用）与 #78144（gateway slash menu symlink 0 skills，当前干净，与 #75130 同根，进备选池）；③ 拉取 upstream main（git fetch --depth=60）成功，后续 tick 可直接对比本地 vs upstream 代码。"
with open(path, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False, indent=2)
print("state updated: tick_count =", st["tick_count"])
print("reports now:", len(st["reports_generated"]))
print("issues now:", len(st["issues_identified"]))
