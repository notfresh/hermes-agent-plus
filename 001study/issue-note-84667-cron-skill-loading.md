# Issue 分析底稿：#84667 Skill 挂 cron job 加载失败（本地验证）

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/84667
> 产出时间：2026-08-13（tick 44，静默时段本地验证）
> 状态：🟢 干净候选（~9h 无 assignee/评论/cross-ref），等用户决策

## 现象（reporter 复现）

同一台机器、同一个 skill 文件（skill-review-gate）：

- `hermes --skills skill-review-gate -z "..."` → ✅ 正常加载，回答正确
- 挂到 cron job（`skills: [skill-review-gate]`）→ ❌ 运行时报：
  `[IMPORTANT: The following skill(s) were listed for this job but could not be found and were skipped: skill-review-gate]`

## 两路径调用链对比（本地源码验证）

```
CLI 路径：
  hermes_cli/main.py:2483  skills 参数进 kwargs
  → cli.py:3632 _parse_skills_argument()（split(",") + strip + 去重）
  → agent/skill_commands.py:725 _load_skill_payload()
  → agent/skill_commands.py:150-152  skill_view(normalized, task_id=task_id, preprocess=False)
  → tools/skills_tool.py:961 skill_view()

cron 路径：
  cron/scheduler.py:2451-2457  skills 字段解析（legacy skill 字段 / str→[str] / strip）
  → cron/scheduler.py:2479  resolve_bundle_command_key()（bundle 检查）
  → cron/scheduler.py:2501  skill_view(normalize_skill_lookup_name(skill_name))   ← preprocess 默认 True！
  → tools/skills_tool.py:961 skill_view()
```

## 关键发现：两路径同源（都走 skill_view），差异在调用参数

skill_view 的查找策略（skills_tool.py:1122-1180：direct path → 分类路径 → 递归按目录名/frontmatter name → 遗留 flat .md）和失败分支（skills_tool.py:1268-1276 平台门、1278-1290 disabled 门）对两条路径**完全相同**。所以"CLI 能找到、cron 找不到"的差异**不在 skill_view 内部**，而在调用参数/进程环境。差异点候选（按可疑度排序）：

### 候选 1：preprocess 参数（最可疑）
- CLI：`preprocess=False`（skill_commands.py:151）
- cron：默认 `preprocess=True`（scheduler.py:2501 没传）

docstring（skills_tool.py:974-977）写明：preprocess=True 会对 SKILL.md 做 **模板替换 + inline shell 渲染**。如果 skill 内容含模板变量/内联 shell 且渲染过程抛异常或产生空内容，cron 路径可能拿不到 content 或返回失败。**验证方法**：给 cron 路径加 preprocess=False 看是否恢复；或检查 skill-review-gate 的 SKILL.md 是否含 `{{...}}`/内联 shell。

### 候选 2：task_id 参数
- CLI：传 `task_id=task_id`（会话 id，skill_commands.py:151）
- cron：不传（默认 None）

skill_view 用 task_id "probe the active backend"——影响是否走远端后端解析。本地后端下影响应该很小。

### 候选 3：cron 进程环境差异
cron 会话以特殊方式启动（skip_memory=True 等），HERMES_HOME/profile/config 若与 CLI 不同 → skills 目录（_skills_dir）、external_dirs、disabled 列表、platform 判定都可能不同。reporter 说"同一进程类型"，但 cron 与 CLI 仍是两个不同的启动路径（main.py cmd_cron vs cli_main），env 不一定一致。

### 候选 4：skills 字段格式（次要点）
- CLI：`_parse_skills_argument` 会 `split(",")`（cli.py:3647）——"a,b" → ["a","b"]
- cron：`isinstance(skills, str)` → `[skills]` 不 split 逗号（scheduler.py:2454-2455）——"a,b" → ["a,b"] 找不到

正常 `hermes cron add --skill x --skill y` 存的是 list（cron.py:43-47 action="append"），此候选只影响字符串格式的字段。

## 教学价值（walkthrough-1/2 的延续素材）

1. **同一个函数、两个调用方、一个参数之差**——`preprocess` 默认值的选择让 CLI（主动关）和 cron（不关）行为分叉。默认参数是 API 设计的一部分，调用方必须显式声明意图。
2. **「找不到 skill」的三层失败面**：cron 层（scheduler.py:2508-2510 warning + skipped 列表）→ skill_view 层（success=False + error 字符串）→ 消息层（[IMPORTANT: ... skipped] 注入 prompt）。每层只看到上一层的结论，看不到根因。
3. 与我们自身运行方式直接相关：本任务（task001）就是 cron + skills 字段加载 github-issues skill，若哪天报同样错误，第一个受害者是我们自己。

## 下一步

- 等用户对 #84667 表态（是否要做）
- 若做：本地复现（构造一个带模板变量的 skill 挂 cron job 对比两路径）→ 确认候选 1 或 3 → 出方案
- 教学：若用户对"两个调用方一个参数"感兴趣，可扩展成 walkthrough 或 teach

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/84667
