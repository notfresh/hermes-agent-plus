#!/usr/bin/env python3
"""tick 50 状态更新：插入新 issue 条目 + 更新元字段"""
import json, sys

STATE = "/root/projects/hermes-agent-plus/001study/task001-state.json"

with open(STATE, encoding="utf-8") as f:
    state = json.load(f)

new_entries = [
    {
        "number": "85145",
        "title": "Sessions wedge permanently on compression exhaustion: the compression_exhausted flag is dropped in TurnRunner.run_sync's normal return path（压缩耗尽后会话永久卡死——flag 只在空响应返回块转发，正常返回块丢弃，gateway 的 auto-reset 机制永远触发不了）",
        "labels": "type/bug, comp/agent, comp/gateway, P1, sweeper:risk-session-state, area/sessions, area/compression",
        "difficulty": "★☆☆（一处遗漏：正常返回块补一行 compression_exhausted 转发；reporter 自带根因+行号，本地已验证）",
        "status": "🟢 干净候选（08-13T18:0X 首查）— 创建 08-13T08:17Z，1 评论（@yun520-1 08:46Z 总结根因，无认领），无 assignee、无 cross-ref PR。⚠️ 高危秒抢型：P1 + reporter 自带根因定位（历史规律：此类 1~2h 内被抢），09:10Z 已被 alt-glitch 标标签。",
        "fix_point": "gateway/run.py 两个返回块不对称：空响应/错误分支 :20978-20998 转发 compression_exhausted（:20988），正常返回块 :21096-21122 缺该字段（有 compacted_in_place 但无 compression_exhausted）→ 下游 :13195 auto-reset（reset_session + :13205 clear_conversation_scope）只认 agent_result.get('compression_exhausted')，永远不触发",
        "fix_idea": "正常返回块补一行 `\"compression_exhausted\": result_holder[0].get(\"compression_exhausted\", False) if result_holder[0] else False`（对齐 :20988 的写法）；需确认 result_holder[0] 是 TurnRunner.run_sync 返回的 agent 结果（flag 由 agent 侧 compression_exhausted=True 传入）。本地验证（08-13T18:0X）：gateway/run.py:20988 确认空响应块转发、:21096-21122 正常块 25 个字段无 compression_exhausted，根因与 issue 描述完全吻合。测试可参考 tests/run_agent/test_1630_context_overflow_loop.py:172-200（TestCompressionExhaustedFlag）。",
        "notes": "🎯 双命中学习重心（compression 机制 teach-14/15 同族 + gateway 状态消息/恢复机制）！教学点：①『哨兵存在但通道断裂』——系统为压缩耗尽设计了完整恢复机制（auto-reset + agent 驱逐 + scope 清理），但 flag 在一条 return 路径上丢失，机制成为死代码；② 双 return 块字段集漂移——空响应块和正常块各自维护字段清单，加字段时只改了一边（与 #84870 三处投影点同族：多处一致假设=多处一致盲区）；③ 与 teach-15（compaction 门控）关联：压缩机制的『事后恢复』环节。待用户决策：想不想做（若做要快，P1 高危）。"
    },
    {
        "number": "85135",
        "title": "Make external memory prefetch timeout configurable (hardcoded 8s is too short for cold Honcho dialectic calls)（外部 memory 预取超时硬编码 8 秒，冷 Honcho 调用 9-11s 被砍，参数已存在但没人接线）",
        "labels": "type/feature, comp/agent, comp/plugins, tool/memory, area/config, P3, area/memory",
        "difficulty": "★☆☆（加配置项 + agent_init 传参；MemoryManager.__init__ 已接受 external_prefetch_timeout 参数，只差调用方接线）",
        "status": "🟢 干净候选（08-13T18:0X 首查）— 创建 08-13T08:04Z，comments=0，无 assignee、无 cross-ref PR。创建后 2h 无人碰，P3 feature 低风险（预计存活窗口较长，但 #79797 先例说明 feature 也可能被秒抢）。",
        "fix_point": "agent/memory_manager.py `_EXTERNAL_PREFETCH_TIMEOUT_S = 8.0` 硬编码常量；MemoryManager.__init__ 已接受 external_prefetch_timeout 参数（带校验、默认常量），但 agent/agent_init.py 实例化时从不传 → 8s 上限实际上不可配置",
        "fix_idea": "① config_defaults.py 加 external_prefetch_timeout 配置项（或复用 memory 节）；② agent_init.py 实例化 MemoryManager 时传入配置值；③ 测试：传自定义值验证超时生效。教学点：『参数已就绪但调用方没接线』的配置传播断点——和 #85028 同模式（能力存在，路径没连通）。",
        "notes": "🎯 命中学习重心（memory 机制 teach-7 关联）！教学点：① 设计意图 vs 实际行为：__init__ 参数齐全暗示『本应可配置』，但实例化点没传 = 参数成为摆设；② 超时语义的取舍：8s 保护冷调用 vs 硬砍正在工作的请求——『宁可失败也不等』的默认值哲学；③ reporter 自带量化（curl 实测 9-11s vs 缓存 1.5s）。与 #85028（tick 48 撞车）『参数存在但路径不传』模式一致。待用户决策。"
    },
    {
        "number": "85123",
        "title": "[Bug]: Redaction registry validators reject safe plugin patterns, and rejection silently stops masking those tokens（redaction 注册表两个新校验器过度拒绝安全模式；register_redaction_patterns fail-soft → 被拒的 token 从此不再被掩码，静默泄漏）",
        "labels": "type/security, comp/plugins, P2, needs-repro",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车 — 创建 08-13T07:41Z，PR #85124 (fix(redact): stop over-rejecting safe plugin redaction patterns, open) 09:11Z cross-ref（~1.5h）。reporter 自带根因（两个 validator commit cfeae1497/50f12e6ad）。弃用（教学素材）。",
        "fix_point": "redaction registry 的两个 validator（拒绝 top-level alternation / ReDoS 形状）过度拒绝：① 每分支带字面前缀的 top-level alternation；② 其他安全形状",
        "fix_idea": "弃用。教学点：『fail-soft by design』的双刃剑——注册失败不阻断启动（好），但意味着过度拒绝 = 秘密静默不再被掩码（坏）；安全校验器的精确性 vs 保守性权衡（误杀一个合法模式 = 一个真实 token 流进日志）。",
        "notes": "按用户规则（security 边界类纳入推荐评估）已核查，但被秒抢出局。教学价值高：redaction registry 校验器的『过度拒绝』设计权衡。"
    },
    {
        "number": "85128",
        "title": "[Bug]: Cron delivery silently dropped and react opaque-id passthrough gone for targets resolve_send_target can't resolve（cron 投递目标解析失败时静默丢弃——resolve_send_target 报错返回 None，caller 当 deliver:local 处理，任务输出凭空消失）",
        "labels": "type/bug, comp/tools, comp/cron, P2, sweeper:risk-message-delivery",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车 — 创建 08-13T07:57Z，PR #85129 (fix(send_message): hand unresolved cron and react targets to the adapt, open) 09:10Z cross-ref（~1.2h）。弃用（教学素材）。",
        "fix_point": "cron/scheduler.py _resolve_single_delivery_target：d409f6748 之后调用 resolve_send_target，解析失败 log warning + return None → caller 等同 deliver:local；之前是回退 raw target 字符串交给 adapter 校验",
        "fix_idea": "弃用。教学点：『解析失败的降级语义』——回退 raw target（让 adapter 最终裁决）vs 返回 None（静默吞掉）的差异；fail-soft 错误面家族又一例（#79472/#85123 同族）。与我们自身 cron 投递直接相关。",
        "notes": "与我们运行方式直接相关（本任务输出就是 cron 投递）。撞车速度快，教学素材。"
    },
    {
        "number": "batch-85145b",
        "title": "08-13 增量批次 2（06:59Z~08:37Z 共 16 条：#85106 RFC citation 规范化、#85110 desktop 隐藏 thinking chrome、#85117 systemd --user scope 查询、#85119 telegram heartbeat 积压、#85125 unified deadline layer tracking、#85127 desktop Windows 侧栏丢历史、#85131 Claude Agent SDK 跳过 approval bridge、#85132 Windows/中文文件乱码、#85136 execute_code venv 污染、#85148 CLI Ctrl+C 可配置、#85149 desktop kanban 全屏、#85153 ACP reasoning_effort none）",
        "labels": "混合",
        "difficulty": "—",
        "status": "🟡 全部记录 — 重点条目已单列（#85145/#85135 候选、#85123/#85128 撞车）。余下：#85131（approval bridge，needs-decision + 修复点模糊）与 #85136（execute_code venv 污染）观察。",
        "fix_point": "—",
        "fix_idea": "不推荐（desktop 5 / telegram 1 / windows 2 / RFC 2 / feature 3 / ACP 1 按规则跳过）",
        "notes": "tick 50 增量扫描（08-13T06:59Z 之后）。无飞书相关。security 类 #85123 已撞车。"
    }
]

state["issues_identified"].extend(new_entries)
state["tick_count"] = 50
state["current_module"] = ("issue_scanning（tick 50：① 候选池大洗牌——#84870 撞车（方向反转：维护者要 independently-listable 两行，三个 PR #84009/#84198/#83987 已存在，@smfworks 明确不写 projection 版，我们钦定方案正是被拒方向）+ #85007 被认领（PR #85171 ranxi2001）；② 新增候选：#85145 P1 compression_exhausted 双 return 块不对称（本地验证 gateway/run.py:20988 vs 21096-21122，高危秒抢型）+ #85135 P3 memory 8s 硬编码超时（参数存在没接线，低风险）；③ #79788 第 13 次仍干净（9 天+）、#84667 第 7 次、#84233 第 10 次全干净；④ 增量 06:59Z~08:37Z 16 条：#85123 security 撞车（PR #85124）、#85128 cron 投递撞车（PR #85129），无飞书；⑤ 走读卡用户未反馈不产新卡）")
state["last_tick_time"] = "2026-08-13T18:0X:00+08:00"
state["notes"] = ("2026-08-13 tick 50（18:0X）：① **复查 5 候选**：#84870 **已撞车且方向反转**——维护者 @jmeadlock 00:09Z 确认复现并提出拍板问题，@smfworks 07:50Z 明确『不写 projection-only 补丁』，三个 independently-listable PR（#84009 CLEAN/#84198/#83987）已存在；我们 tick 49 钦定的三处投影点方案正是维护者不要的；#85007 **被认领**（@ranxi2001 08:17Z 认领 + PR #85171）；#79788 第 13 次仍干净（9 天+ updated 停创建日）；#84667 第 7 次（~24h）；#84233 第 10 次（~39h）。② **增量扫描**：06:59Z~08:37Z 16 条——**新候选 #85145**（P1 compression_exhausted 双 return 块不对称，本地验证 gateway/run.py:20988 空响应块转发 / :21096-21122 正常块 25 字段无此 flag / :13195 auto-reset 永不触发，根因吻合；高危秒抢型）、**新候选 #85135**（P3 memory 预取 8s 硬编码，参数已存在没接线，低风险长寿型）；security 类 #85123 与 cron 投递 #85128 均 ~1.5h 内撞车（PR #85124/#85129）。③ **认证**：匿名 API（issues 5 + comments 2 + timeline 2 + search 1 + pulls 2 = 12 次），配额充足。④ 教学读代码：walkthrough-4 已产出待用户反馈，不产新卡。⚠️ 候选现状：#79788（9 天+ 干净）、#84667（~24h）、#84233（~39h）、#85145（P1 高危，要做得快）、#85135（P3 低危）——等用户决策选哪个做。")

with open(STATE, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("OK: tick_count =", state["tick_count"], "| issues =", len(state["issues_identified"]))
