#!/usr/bin/env python3
"""tick 70 状态文件更新"""
import json

PATH = "/root/projects/hermes-agent-plus/001study/task001-state.json"
s = json.load(open(PATH))

# 1. tick 计数与摘要
s["tick_count"] = 70
s["current_module"] = (
    "tick 70（08-23 09:0X）暂停中例行复查日（第 27 轮）——awaiting_answer 仍 true（用户 08-17 索取 "
    "walkthrough-4 后任务001群无回复，08-19~23 用户在求职/kimi/其他 feishu 群活跃，08-23 早上还在配群）。"
    "候选池第 27 轮复查：4 个老候选撞车——#89050（双 PR #89051+#89105，config warn vs cli validate 两种修法竞争）/"
    "#89502（PR #89504）/ #89560（3 PR：#89563+#89568+#89851）/ #90315（3 PR：#90421 open + #90676/#90724 closed）。"
    "存活：#79788 第 25 次仍干净（17 天+ 无人碰，头号不动摇）、#85135 第 11 次仍干净（10 天）、#84233 仍无 PR 但 "
    "reporter/复现者亲自跟进风险续涨、#89158 仍干净（security）、#89515 仍干净（perf 类收割慢）、#90366 仍干净（同族 "
    "#89547 已撞，风险极高）。增量扫描（08-19T09:00Z 后 4 天，共 765 条新 issue，日流速 ~190 条）：高价值候选几乎全被秒抢——"
    "#91308 auxiliary 凭据泄露（双 PR #39602+#91331）/ #92313 新装 skill gateway 不可见（PR #92320 当天）/ #90004 skill env var"
    "（PR #90011 当天）/ #90040 external_dirs Managed Scope（PR #90052 当天）/ #90833 Feishu stale DM（PR #90927）/ "
    "#92063 Feishu 流式分段冻结（PR #92067 当天）/ #89938 HTTP 413 loop（3 PR）/ #90699 TUI RPC 逃逸（双 PR #90715+#91488，"
    "21 分钟秒抢）/ #90700 /api/status 泄露（PR #90750）/ #91442 curator delete 假成功（双 PR #91457+#91464）。"
    "新存活 5 个：#90009 delegate_task fallback 凭据错配（reporter 带完整离线复现，4 天）/ #90173 compression SQLite 锁 "
    "25-140s（P2，4 天）/ #90177 session poisoning（P2，4 天）/ #89961 pinned skills 可写（security+skill 双命中，4 天）/"
    "#89912 web_search 从 agent.tools 消失（liuhao1024 已排查说环境特定，修复点模糊，降级观察）。规律验证：skill/tool 加载类"
    "几乎 100% 当天被抢；多 provider 组合类（fallback/本地模型）收割慢。delivery = 暂停消息 + 撞车通报 + 新候选清单。"
)

# 2. 更新已有条目 status
status_updates = {
    79788: "🟢 干净候选（08-23 tick 70 第 25 次复查）— 仍 open、updated 停 08-06T00:25Z（创建日）、comments=0 assignees=0、timeline 仅 labeled、无 cross-ref，17 天+ 无人碰。头号候选不动摇。",
    85135: "🟢 干净候选（08-23 tick 70 第 11 次复查）— 仍 open、updated 停 08-13（创建日）、comments=0 assignees=0、timeline 仅 labeled，10 天无人碰，仍干净。",
    84233: "🟡 无变化（08-23 tick 70 第 18 次复查）— 仍 open、comments=1（@TheOpie 08-14 macOS 复现）、无 assignee、timeline 无 PR cross-ref（仅 2 个相关 issue 引用 #73722/#79742）。reporter/复现者亲自跟进，撞车风险续涨。",
    89050: "🔴 已撞车（08-23 tick 70 确认）— timeline 双 PR：#89051（fix(config): warn when platform_toolsets entry is empty）+ #89105（fix(cli): validate per-platform），互 cross-ref 竞争，都 open。tick 68 首查时还干净，~2 天被双 PR 拿下。",
    89502: "🔴 已撞车（08-23 tick 70 确认）— timeline PR #89504（fix(model_metadata): parse llama.cpp exceed_context_size_error）已出。创建 08-18T21:50，被抢。",
    89560: "🔴 已撞车（08-23 tick 70 确认）— 3 PR 竞争：#89563+#89568+#89851（fix(cron): re-parse own once-at/once-in display）。创建 08-18T23:46，1 天+ 内三连。",
    90315: "🔴 已撞车（08-23 tick 70 确认）— 3 PR 竞争：#90421（open）+ #90676（closed）+ #90724（closed）。security 边界类但 health 端点开放是常见设计，修复方向分叉，观察 PR 走向即可。",
    90366: "🟢 干净候选（08-23 tick 70 第 2 次复查）— 仍 open、updated 停 08-20T00:01、comments=0、无 assignee、timeline 仅 labeled。⚠️ 与已撞车 #89547 同族（toolset 平台解析），liuhao1024 活跃，撞车风险极高。",
    90393: "🟡 观察（08-23 tick 70 复查）— 1 comment（triage），needs-repro + 模型特定（native reasoning），本地无法验证。",
}

# 3. 新增条目
new_entries = [
    {
        "number": 90009,
        "title": "delegate_task inherits parent's post-fallback provider-mismatched credential — instant 401, no retry（父会话 fallback 后 delegate 子代理保留 primary endpoint 却用 fallback 凭据）",
        "labels": "type/bug, comp/agent, tool/delegate, provider/*, needs-repro",
        "difficulty": "★★☆（reporter 自带合成离线复现；修复点：delegation 配置继承链的 provider/base_url/credential 三元组传递）",
        "status": "🟢 干净候选（08-23 tick 70 首查，08-19T13:36 创建，4 天无人碰）— open、comments=1（reporter 自带离线复现回应 needs-repro）、无 assignee、search 无关联 PR。",
        "fix_point": "delegate_task 子代理的 provider/base_url/credential 继承（父 fallback 后 agent.provider 与 client 端点的错配沿 delegation 链传递）",
        "fix_idea": "待读代码定位 delegation 参数继承；方向：spawn 子代理时固化 provider+base_url+credential 三元组（fallback 后取 agent 当前实际 client 配置而非 primary 配置）。验收：父 fallback 到 anthropic 后 delegate → 子代理用 anthropic 端点+凭据。",
        "notes": "🎯 命中学习重心（fallback 机制，teach-12 同族）！多 provider 组合类 bug 收割慢（需特定环境复现）——与秒抢规律相反的观察样本。reporter 评论给出完整离线合成复现，修复验证可行性高。",
    },
    {
        "number": 90173,
        "title": "Context compression holds SQLite write lock 25-140s, blocking gateway and desktop sessions",
        "labels": "type/bug, comp/agent, comp/gateway, P2, area/compression, area/sessions",
        "difficulty": "★★☆（压缩期间持锁窗口优化：写事务分块/降级读）",
        "status": "🟢 干净候选（08-23 tick 70 首查，08-19T17:48 创建，4 天无人碰）— open、comments=0、无 assignee、search 无关联 PR。",
        "fix_point": "context_compressor/archive_and_compact 的 SQLite 写事务持锁窗口（25-140s）",
        "fix_idea": "待读压缩事务代码；方向：压缩写操作分块提交、或压缩期间用 WAL 模式+读快照隔离 gateway 读路径。",
        "notes": "🎯 命中学习重心（压缩机制，teach-15 同族 + 会话存储）。P2 但修复需理解压缩事务边界，复杂度适中。",
    },
    {
        "number": 90177,
        "title": "Persistent session poisoning: bracketed traceback text stored in state.db poisons future turns",
        "labels": "type/bug, comp/agent, provider/openrouter, P2",
        "difficulty": "★★☆（traceback 文本入库的清洗/隔离）",
        "status": "🟢 干净候选（08-23 tick 70 首查，08-19T18:01 创建，4 天无人碰）— open、comments=0、无 assignee、search 无关联 PR。",
        "fix_point": "state.db 会话消息存储前的 traceback 清洗（或读取时的过滤）",
        "fix_idea": "待读消息持久化路径；方向：写库前对工具错误消息做 traceback 块剥离/折叠。",
        "notes": "🎯 命中学习重心（会话管理 + 消息清洗，teach-13 message-repair 同族）。P2。",
    },
    {
        "number": 89961,
        "title": "Pinned skills are writable from foreground origins that have no user in the loop（pinned skill 可从无用户在场的 foreground 源写入）",
        "labels": "type/feature, comp/agent, comp/cron, tool/skills, P3, needs-decision",
        "difficulty": "★★☆（feature + needs-decision，写权限来源判定）",
        "status": "🟢 干净候选（08-23 tick 70 首查，08-19T11:13 创建，4 天无人碰）— open、comments=0、无 assignee、search 无关联 PR。security 边界类（用户 2026-08-13 规则纳入推荐范围）。",
        "fix_point": "pinned skill 写权限的来源校验（foreground origin 无人在环时不应可写）",
        "fix_idea": "待读 skill 写权限链；needs-decision 方向未定，撞车/被关风险中。",
        "notes": "security 边界 + skill 机制双命中。feature 类 + needs-decision，参考历史规律（needs-decision 也挡不住收割）风险中。",
    },
    {
        "number": 89912,
        "title": "web_search registered but removed from live agent.tools with DDGS and local Ollama（DDGS+Ollama 场景 web_search 注册了却不传给模型）",
        "labels": "type/bug, comp/agent, comp/plugins, tool/web",
        "difficulty": "★★★（liuhao1024 已排查 tool-assembly 全链未找到分叉点，疑似环境特定）",
        "status": "🟡 观察（08-23 tick 70 首查，08-19T11:09 创建，4 天存活但被盯上）— open、comments=2（liuhao1024 排查评论：'two web tools share a fate at every layer'，根因疑似环境特定；reporter 回复环境细节）、无 assignee、无 PR。",
        "fix_point": "待定位（tool-assembly 链各层两工具命运相同，差异来自环境特定因素）",
        "fix_idea": "不主动推荐：修复点模糊（老手排查过无结论）+ liuhao1024 盯盘中。作教学素材（tool 装配链逐层对比排查法）。",
        "notes": "🎯 命中学习重心（tool 系统加载，walkthrough-4 同域）但修复点模糊。liuhao1024 的排查评论本身有教学价值（'share a fate at every layer'——排除法思路）。",
    },
    {
        "number": 89963,
        "title": "background review codifies session content into skills with a 'Verified' label without human verification",
        "labels": "type/feature, comp/agent, tool/skills, P3, needs-decision",
        "difficulty": "—（feature + needs-decision）",
        "status": "🟡 观察（08-23 tick 70 首查）— open、无 assignee。疑似关联 PR #90883（security: restore session write and self-improvement enforcement，body 未直接引用本 issue，待确认）。",
        "fix_point": "background review → skill 写入的验证链",
        "fix_idea": "不推荐。",
        "notes": "skill 机制沾边，feature+needs-decision。观察 PR #90883 是否覆盖。",
    },
    {
        "number": 91308,
        "title": "Auxiliary custom-endpoint calls send OPENAI_API_KEY to any host (shadowing + credential leak)",
        "labels": "type/security, comp/agent, area/auth, P2",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 首查即撞）— 双 PR：#39602（老 PR）+ #91331（fix(aux): gate OPENAI_API_KEY on OpenAI hosts）。创建 08-21T05:10，当天被抢。",
        "fix_point": "auxiliary client 的 api_key 发送目标 host 校验",
        "fix_idea": "弃用。",
        "notes": "security 边界类 + auxiliary client（#79788 同域）！教学点：凭据按 host 门控（与 #79788 的 URL 重写同域，两个 issue 一起看 auxiliary client 的配置面）。",
    },
    {
        "number": 92313,
        "title": "Newly installed skills invisible to running gateway: stale in-process _SKILLS_PROMPT_CACHE",
        "labels": "type/bug, comp/agent, tool/skills, P2",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 首查即撞）— PR #92320（fix(prompt): invalidate skills index LRU when skill...）创建 08-22T15:11，当天被抢。",
        "fix_point": "prompt_builder 的 _SKILLS_PROMPT_CACHE LRU 失效时机（skill 安装后不失效）",
        "fix_idea": "弃用。教学点：三级缓存（walkthrough-1）的失效时机——新 skill 安装不触发索引失效，运行中 gateway 永远看不到。",
        "notes": "🎯 直接命中 walkthrough-1 的三级缓存主题！撞车但教学价值极高——缓存失效时机是缓存设计的另一半。",
    },
    {
        "number": 90004,
        "title": "Skill-declared env var (prerequisites.env_vars) not passed through to execute_code on first use",
        "labels": "type/bug, tool/terminal, tool/skills, tool/code-exec, area/config",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 首查即撞）— PR #90011（fix(skills): make env_passthrough registrations vi...）创建当天被抢。",
        "fix_point": "skill prerequisites.env_vars → execute_code 的 env 传递链",
        "fix_idea": "弃用。教学点：skill 声明（frontmatter env_vars）→ 运行时 env 注册 → 工具执行注入 的完整链路。",
        "notes": "🎯 命中学习重心（skill 加载→执行链）。撞车。",
    },
    {
        "number": 90040,
        "title": "skills.external_dirs ignores Managed Scope and must be duplicated per profile",
        "labels": "type/bug, tool/skills, area/config, P2",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 首查即撞）— PR #90052（fix(skills): honor Managed Scope for skills.extern...）创建当天被抢。",
        "fix_point": "skills.external_dirs 的 Managed Scope/profile 作用域处理",
        "fix_idea": "弃用。教学点：配置作用域（global vs profile vs managed）与 skill 目录解析。",
        "notes": "🎯 命中学习重心（skill 目录加载）。撞车。",
    },
    {
        "number": 90833,
        "title": "Feishu: stale inbound DM (create_time 11:41) delivered ~7h later despite healthy response",
        "labels": "type/bug, comp/plugins, platform/feishu, P3",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 首查即撞）— PR #90927（fix(feishu): drop stale inbound events whose creat...）创建 08-20T13:29，当天被抢。",
        "fix_point": "feishu adapter 入站事件的新鲜度过滤（create_time 与当前时间差）",
        "fix_idea": "弃用。",
        "notes": "飞书类（用户规则纳入推荐）但被秒抢。",
    },
    {
        "number": 92063,
        "title": "[Bug][Feishu]: mid-turn segment break freezes the streamed bubble (stuck cursor) and splits text",
        "labels": "type/bug, comp/gateway, platform/feishu, P2",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 首查即撞）— PR #92067（fix(streaming): seal the segment-break bubble stri...）创建 08-22T05:08，当天被抢。",
        "fix_point": "feishu 流式消息分段（segment break）的 bubble 封口",
        "fix_idea": "弃用。",
        "notes": "飞书流式体验 bug，用户日常使用直接相关，但被秒抢。",
    },
    {
        "number": 89938,
        "title": "HTTP 413 loop: base64 images in tool results re-ship on every turn until provider rejects",
        "labels": "type/bug, comp/agent, tool/vision, P2, area/compression",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 确认）— 3 PR：#89965（bound historical image payloads）+ #90001（age out stale tool-result images）+ #88960（recover from image-dominated 413）。",
        "fix_point": "tool 结果中 base64 图片的逐轮重发（历史图片无界累积）",
        "fix_idea": "弃用。教学点：工具结果载荷的生命周期管理（与压缩机制交织）。",
        "notes": "🎯 命中 agent 核心循环（tool 结果处理）。3 PR 竞争说明修复方向分叉。",
    },
    {
        "number": 90699,
        "title": "TUI gateway RPC profile param escapes profiles root — no validation (path traversal)",
        "labels": "type/security, comp/tui, P2, needs-repro",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 确认）— 双 PR：#90715 + #91488（都是 fix(tui): validate the RPC profile param）。创建 08-20T09:31，PR #90715 当天 09:52 出（21 分钟秒抢）。",
        "fix_point": "tui_gateway RPC 的 profile 参数路径校验",
        "fix_idea": "弃用。",
        "notes": "security 边界类，秒抢纪录（21 分钟）。",
    },
    {
        "number": 90700,
        "title": "Public /api/status returns unfiltered platform error_messages (info leak)",
        "labels": "type/security, P2, needs-repro",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 确认）— PR #90750（fix(dashboard): stop leaking free-text platform error_message）。创建 08-20T09:31，1 小时被抢。",
        "fix_point": "dashboard /api/status 的 error_message 过滤",
        "fix_idea": "弃用。",
        "notes": "security 边界类。",
    },
    {
        "number": 91442,
        "title": "curator: skill_manage delete reports success but leaves skill dir in place",
        "labels": "type/bug, comp/agent, tool/skills, P2",
        "difficulty": "—（已撞车）",
        "status": "🔴 已撞车（08-23 tick 70 确认）— 双 PR：#91457（verify live dir gone before reporting）+ #91464（pass exact skill_dir to archive_skill）。创建 08-21T10:34，17 分钟被抢（纪录再刷新）。",
        "fix_point": "curator skill_manage delete 的成功判定（目录是否真删）",
        "fix_idea": "弃用。教学点：'报告成功但副作用未发生' bug 型（与 #79472 memory 静默失败同族）。",
        "notes": "skill 机制命中学习重心，双 PR 竞争。",
    },
]

# 应用 status 更新
for e in s["issues_identified"]:
    if e["number"] in status_updates:
        e["status"] = status_updates[e["number"]]

# 追加新条目（避免重复）
existing_nums = {e["number"] for e in s["issues_identified"]}
for ne in new_entries:
    if ne["number"] not in existing_nums:
        s["issues_identified"].append(ne)

# 4. notes 追加
s["notes"] += (
    "\n\n2026-08-23 tick 70（09:0X）：⏸ 仍暂停（awaiting_answer=true，用户 08-17 后任务001群无回复；"
    "08-19~23 用户在求职/kimi/其他群活跃）。第 27 轮候选池复查：4 老候选撞车（#89050 双 PR / #89502 PR#89504 / "
    "#89560 3 PR / #90315 3 PR）；#79788 第 25 次仍干净（17 天+，头号）、#85135 第 11 次仍干净、#84233 仍无 PR（风险续涨）、"
    "#89158/#89515/#90366 仍干净。增量扫描 08-19T09:00Z 后 4 天共 765 条新 issue（日流速 ~190！），高价值候选几乎全被秒抢："
    "#91308（auxiliary 凭据泄露，双 PR）/ #92313（skill 缓存失效，PR#92320 当天）/ #90004（skill env var，当天）/ "
    "#90040（external_dirs，当天）/ #90833+#92063（飞书 2 条，当天）/ #89938（413 loop，3 PR）/ #90699（21 分钟秒抢纪录）/ "
    "#90700 / #91442（17 分钟，纪录再刷新）。新存活 5 个：#90009（fallback 凭据错配，带离线复现）/ #90173（压缩持锁）/ "
    "#90177（session poisoning）/ #89961（pinned skills security）/ #89912（web_search 消失，liuhao1024 已排查说环境特定，降级观察）。"
    "规律强化：skill/tool 加载类 ~100% 当天被抢；多 provider 组合类（fallback/本地模型）收割慢（4 天存活），是仅存的推荐窗口。"
    "API 配额：gh 未登录、.env token 被注释，全程匿名 60/h（用尽后等 reset 或网页抓取兜底）。delivery = 暂停消息 + 撞车通报 + 新候选。"
)

json.dump(s, open(PATH, "w"), ensure_ascii=False, indent=2)
print(f"状态文件更新完成：tick={s['tick_count']}, issues_identified={len(s['issues_identified'])} 条")
