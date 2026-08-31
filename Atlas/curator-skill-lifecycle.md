# Curator：技能自动生命周期管理

> 基于 `feature.skill-curator` 的 AX-GRAPH 调用图 + 源码逐行核实（2026-08-31）。
> 核心代码：`agent/curator.py`、`tools/skill_manager_tool.py`、`tools/skill_usage.py`、`tools/skill_provenance.py`

---

## 一、直觉：这玩意是干嘛的？

Hermes 的"自我改进循环"会让 agent 解决新问题后自己写 skill 存进 `~/.hermes/skills/`。副作用：**技能越堆越多**——三个功能重叠 80% 的 PDF 技能并存，每次对话都要把技能清单发给模型（吃 token），目录越乱越难选对。

curator（curator = 图书管理员）解决这个问题：**一个定期醒来的后台任务**，类比图书馆管理员：

- 一本书 30 天没人借 → 贴"待处理"标签（**stale**）
- 90 天还没人碰 → 搬进地下室归档（**archive**，可恢复，不销毁）
- 三本内容重复的笔记 → 合并成一本总纲，旧的撤架（**consolidate**）

**关键边界**：只动"agent 自己创建的技能"。手动写的、官方自带的（bundled）、技能市场装的（hub）、外部目录的、钉住的（pinned）——一律不碰。

> 官方文档原文："It exists so that skills created via the self-improvement loop don't pile up forever. ... Without maintenance, you end up with dozens of narrow near-duplicates that pollute the catalog and waste tokens."

---

## 二、默认配置（`agent/curator.py:70-73`）

| 配置 | 默认值 | 含义 |
|------|:----:|------|
| `interval_hours` | **168 (7 天)** | 距上次运行 ≥ 7 天才再跑 |
| `stale_after_days` | **30** | 30 天没使用 → 标 stale |
| `archive_after_days` | **90** | 90 天没使用 → 归档 |
| `consolidate` | **off** | LLM 合并评审默认关（省 aux-model 费用） |
| `prune_builtins` | **on** | 内置技能也参与陈旧判定（可归档，不可删） |

本机实况（`hermes curator status`，2026-08-31）：

```
curator: ENABLED   runs: 6   last run: 1d ago
last summary: auto: 59 marked stale; llm: skipped (consolidation off)
curator-managed skills: 139 total (agent-created=61 bundled=78)
  active 77  stale 62  archived 0
```

---

## 三、状态机：active → stale → archived

判定逻辑（`apply_automatic_transitions`，`agent/curator.py:305`，纯函数无 LLM）：

```python
# curator.py:321-322  两条时间线
stale_cutoff   = now - timedelta(days=30)   # 30 天没动静 → stale
archive_cutoff = now - timedelta(days=90)   # 90 天没动静 → archived

# curator.py:328  逐个技能检查
for row in agent_created_report():           # 所有"curator 管得着"的技能
    if row.get("pinned"): continue          # 钉住的技能永远不碰
    anchor = last_activity or created_at    # 最近使用时间，没用过就算创建时间
    if anchor <= archive_cutoff:  archive_skill(name)   # 90天 → 归档
    elif anchor <= stale_cutoff:  set_state(name, STALE) # 30天 → 标旧
    elif 又用了:                   set_state(name, ACTIVE) # 复活
```

规则细节（源码注释，`curator.py:334-381`）：

- **cron 引用的技能 = 永不移除**（`:340`）：cron 作业引用过（含暂停/禁用）的技能视为"在用"，因为调度器只在作业真正触发时才记 usage，低频作业的技能不该被误杀
- **pinned = 永不碰**（`:331`）：用户显式钉住
- **use_count=0 的技能有宽限期**（`:363-369`）：没用过的技能只要比 stale 窗口年轻就不动——"absence of evidence ≠ evidence of staleness"，新技能可能只是还没等到触发场景
- **归档 ≠ 删除**：目录搬到 `~/.hermes/skills/.archive/`（`skill_usage.py:697`），可 `hermes curator restore` 恢复；**自动删除永远不会发生**

---

## 四、主调用链（AX-GRAPH 调用图 + 实测行号）

```
gateway 定时 tick / 会话启动钩子
  └─ maybe_run_curator            agent/curator.py:1998   ← 入口（无 CALLS 入边）
      ├─ should_run_now()          curator.py:233         门槛：enabled、未暂停、距上次≥7天
      └─ run_curator_review()      curator.py:1494        主流程
          ├─ snapshot_skills()     curator.py:1550        先打快照（真跑才打，可 rollback）
          ├─ apply_automatic_transitions()  curator.py:1559 → 305   ← 免费段
          │     └─ agent_created_report()   skill_usage.py:870  ← 列可管理技能
          │     └─ archive_skill()          skill_usage.py:696  ← 90天没动→搬 .archive/
          ├─ 保存 .curator_state   curator.py:1575-1581
          └─ _llm_pass()           curator.py:1583        闭包；consolidate 关→直接返回
              └─ _run_llm_review(prompt)   curator.py:1677 → 1825   ← 付费段（默认跳过）
                  └─ fork AIAgent          curator.py:1848
                      └─ [子 agent 循环内] 工具调用 skill_manage
                          └─ skill_manage    tools/skill_manager_tool.py:1340
                              ├─ _background_review_preflight   :1357 → :429
                              │    └─ _background_review_write_guard :297
                              ├─ 执行 create/patch/delete       :1374-1407
                              └─ 成功遥测标记                    :1421-1436
                                   └─ mark_agent_created        skill_usage.py:646
```

### 调用图里那个 `@ ?` 是什么？

`_run_llm_review → skill_manage @ ?` —— 调用点是问号，因为 `_run_llm_review`（`curator.py:1825`）**根本不直接调用 skill_manage 函数**：

```python
# curator.py:1848
from run_agent import AIAgent   # fork 出一个全新的 agent
```

它 fork 一个子 AIAgent，把评审 prompt 丢过去，子 agent **在自己的 agent 循环里通过工具调用（tool call）执行 skill_manage**。curator 的"智能部分"不是函数调用，而是又一个完整的 agent 会话：模型 → 看候选技能列表 → 决定 create/patch/delete → 拿工具结果 → 继续，直到输出最终报告。这是 agent 核心循环的活体样本。

### 两段式设计：免费段 + 付费段

| 阶段 | 干什么 | 成本 | 默认 |
|------|--------|:----:|:----:|
| 自动转移（纯 Python，`curator.py:305`） | 按时间戳标 stale / 归档 | 0 token，确定性 | **开** |
| LLM 评审（fork AIAgent，`curator.py:1825`） | 读内容，提议合并/打补丁 | aux-model 费用 | **关** |

`curator.py:1596` 注释原文：consolidate 关时 "the curator does ONLY the deterministic inactivity prune ... no aux-model cost"。**基础维护免费自动跑，智能增值服务按需付费** —— YAGNI 在生产代码里的样子。

---

## 五、三层护栏（自治系统安全的关键）

护栏全部写在 **skill_manage 工具函数内部**（`tools/skill_manager_tool.py`），而不是写在 curator 的 prompt 里。prompt 说"别删"是请求，工具层检查是**强制**——LLM 可以无视 prompt，绕不过工具代码。**工具即边界**。

### 护栏 1：写保护 —— 谁有权动谁（`:297`）

后台评审 fork 是"无人值守的自治维护"，写权限收得很窄，依次拒绝（`skill_manager_tool.py:297-396`）：

| 检查 | 行为 |
|------|------|
| pinned 技能（`:324`） | 拒绝（autonomous 无人在场，比前台更严——前台只拦删除，后台拦一切写） |
| 外部目录技能 `is_external_skill_path`（`:339`） | 拒绝（外部拥有，只读） |
| 受保护内置 `is_protected_builtin`（`:353`） | 拒绝（承载关键 UX） |
| hub 安装技能（`:361`） | 拒绝（有外部上游） |
| bundled 内置（`:369`） | 拒绝（官方自带） |
| **非 agent 创建**（`:384`，`created_by != "agent"`） | 拒绝（手动写的技能不在管辖范围） |

识别依据：**contextvars 写来源标记**。`skill_provenance.py:75` 的 `is_background_review()` 读 `_write_origin` 上下文变量——只有后台评审 fork 的上下文里它才是 `"background_review"`（`skill_provenance.py:45`）。用 contextvars 而非全局变量，是因为子 agent 是 fork 的独立上下文，全局变量会被并发会话串扰。

### 护栏 2：先读再写（`:399`）

后台评审 fork 想改技能，必须**先在本轮对话里调用过 skill_view 读过目标文件**（`_background_review_has_read`，`:413`），否则拒绝——防止 LLM 没看内容就瞎 patch。错误信息直接告诉它：`Call skill_view(name) ... then retry the write using the content just returned`（`:420-424`）。

### 护栏 3：删技能必须声明"并进哪本了"（`:438`）

`_curator_consolidation_delete_guard` 的注释记录了一场真实事故（**issue #29912**）：以前 LLM 合并时把整个集群的活跃技能全删了，而实际合并一个都没发生（`consolidated_this_run == 0`），导致自动化任务指向的技能全部失联。修复：**fail closed** —— 后台评审的 `skill_manage(action=delete)` 必须带 `absorbed_into=<伞技能名>` 且伞技能真实存在，否则拒绝（`:449-457`）。你平时在 skill_manage 工具里看到的 `absorbed_into` 参数就是这场事故的遗产。

### 兜底：快照 + 账本

- 每次真跑前自动打 tar.gz 快照（`curator.py:1550-1551`）→ `hermes curator rollback` 可整体回滚
- `hermes curator ledger` 记录每一次改动的审计日志（谁/何时/动了什么）
- `--dry-run` 干跑只写报告不动任何文件（`curator.py:1531-1542`）

---

## 六、CLI 全景（`hermes curator --help`）

```
status           状态与技能统计          usage    全部技能使用遥测+来源
run              立刻跑一次评审          pause/resume  暂停/恢复
pin / unpin      钉住/解除（curator 永不碰）
adopt            把无来源标记的技能交给 curator 管理（来源=用户声明）
restore          恢复归档技能            list-archived  列出归档
archive          手动归档               prune    批量归档闲置≥N天（默认90）
backup/rollback  手动快照 / 回滚         ledger   逐条审计日志
purge            删除归档超 TTL 的（仅显式，永不自动）
```

---

## 七、设计启示（关联层）

1. **curator = 多个核心概念的集合体**：cron（定时触发）+ agent 核心循环（fork AIAgent）+ tool 系统（skill_manage）+ 自我改进（技能沉淀）——读通它等于串起整个 agent 体系
2. **自治系统的核心不是聪明，是边界**：LLM 部分只是"看看列表提提议"，真正让它安全的是 provenance 检查 + 先读再写 + absorbed_into + 快照回滚。**给 AI 权力时必须划定边界**
3. **工具层是唯一执法点**：护栏在工具函数内部而非 prompt——模型可无视提示词，绕不过代码。设计自己的 agent 时，禁止事项写进工具逻辑，不要只写进提示词
4. **与 agent 记忆设计同源**：active/stale/archived 三级状态 + 时间衰减 + 可恢复归档，就是技能版的"知识生命周期判别"（对应 `agent-memory-design` 框架）——记忆系统设计的生产级亲兄弟

---

## 附：关键行号速查

| 函数 | 位置 |
|------|------|
| `maybe_run_curator` | `agent/curator.py:1998` |
| `should_run_now` | `agent/curator.py:233` |
| `apply_automatic_transitions` | `agent/curator.py:305` |
| `_parse_structured_summary` | `agent/curator.py:737` |
| `run_curator_review` | `agent/curator.py:1494` |
| `_run_llm_review` | `agent/curator.py:1825` |
| `skill_manage` | `tools/skill_manager_tool.py:1340` |
| `_background_review_write_guard` | `tools/skill_manager_tool.py:297` |
| `_background_review_read_before_write_guard` | `tools/skill_manager_tool.py:399` |
| `_background_review_preflight` | `tools/skill_manager_tool.py:429` |
| `_curator_consolidation_delete_guard` | `tools/skill_manager_tool.py:438` |
| `is_background_review` | `tools/skill_provenance.py:75` |
| `agent_created_report` | `tools/skill_usage.py:870` |
| `archive_skill` | `tools/skill_usage.py:696` |
| `is_agent_created` | `tools/skill_usage.py:419` |
| `mark_agent_created` | `tools/skill_usage.py:646` |
