## Hermes 命令执行时 Skill 加载场景分析

基于 AX-GRAPH 的 `Layer-3-Graph-skill_startup.toml` 和 `Layer-3-Graph-skill_load.toml`。

---

### 一、两种"加载"的本质区别

| 阶段 | 叫什么 | 做什么 | 产出 |
|------|--------|--------|------|
| **启动时** | 技能索引注入 | 把技能**名+描述**注入 system prompt | 让 agent "感知"有哪些技能可用 |
| **运行时** | 载荷加载 | 用户调用 `/skill xxx` 时读取 **SKILL.md 全文** | 技能的实际操作指引 |

> **关键澄清**：AGENTS.md 说的"加载 skill"是**启动注入**（索引），不是运行时读全文。

---

### 二、启动链：`hermes` 命令 → 技能索引注入

```
hermes 命令
    │
    ▼
main() [main.py:13206]
    │ args.func 分发
    ▼
cmd_chat() [main.py:2295]
    │ ├─ 同步 bundled 技能
    │ └─ 调用 cli.main()
    ▼
cli.main() [cli.py:15384]
    │ 会话循环
    ▼
_init_agent() [cli_agent_setup_mixin.py:226]
    │ 实例化 AIAgent
    ▼
AIAgent.__init__() [run_agent.py:399]
    │ 初始化工具、缓存
    ▼
run_conversation() [run_agent.py:6329]
    │ 转发给主循环
    ▼
conversation_loop.run_conversation() [conversation_loop.py:588]
    │ 首 turn 构建上下文
    ▼
turn_context.build_turn_context() [turn_context.py:268]
    │ 判定 _cached_system_prompt is None
    ▼
_restore_or_build_system_prompt() [conversation_loop.py:304]
    │ 恢复或首次构建
    ▼
AIAgent._build_system_prompt() [run_agent.py:3815]
    │ 转发
    ▼
agent.system_prompt.build_system_prompt() [system_prompt.py:527]
    │ 组装三层 prompt
    ▼
build_system_prompt_parts() [system_prompt.py:147]
    │ 判定 has_skills_tools → 调用技能索引构建
    ▼
★ build_skills_system_prompt() [prompt_builder.py:1490] ★
    │ 技能索引三层缓存
    ▼
注入 stable 层 → agent 感知技能列表
```

---

### 三、build_skills_system_prompt 的三层缓存机制

```python
def build_skills_system_prompt():
    # L1: 进程内 LRU 缓存（内存）
    if cached: return cache
    
    # L2: 磁盘快照 (.skills_prompt_snapshot.json)
    snapshot = _load_skills_snapshot()
    if snapshot.valid:
        return snapshot
    
    # L3: 冷扫描（首次或快照失配）
    skills = []
    for path in iter_skill_index_files():      # agent/skill_utils.py:797
        frontmatter = _parse_skill_file(path)  # 读 SKILL.md
        if _skill_should_show(frontmatter):   # 过滤
            skills.append(_build_snapshot_entry(...))
    
    _write_skills_snapshot(skills)  # 写盘复用
    return format_skills_prompt(skills)
```

**过滤链**（at_line:316 调用后）：
1. **平台兼容** → `skill_matches_platform_list()` (Linux/Mac/Windows)
2. **禁用名单** → `get_disabled_skill_names()` (config.yaml)
3. **工具条件** → `_skill_should_show()` (frontmatter conditions)

---

### 四、运行时载荷加载：`/skill` 命令触发

```
用户输入 /skill <name>
    │
    ▼
resolve_skill_command_key() [skill_commands.py:496]
    │ 把命令键解析为技能标识
    ▼
_load_skill_payload() [skill_commands.py:138] ★核心
    │ ├─ skill_view() 读取 SKILL.md 全文
    │ ├─ preprocess_skill_content() 模板替换
    │ └─ 返回 (payload, dir, display_name)
    ▼
skill_view() [skills_tool.py:961]
    │ CLI/cron 两路径汇聚点
    ▼
scan_bundles() [skill_bundles.py:168]
    │ 扫描技能包
    ▼
返回技能全文内容给 agent
```

---

### 五、关键文件与职责

| 文件 | 核心函数 | 职责 |
|------|----------|------|
| `agent/prompt_builder.py` | `build_skills_system_prompt()` | 启动时构建技能索引（三层缓存） |
| `agent/skill_utils.py` | `iter_skill_index_files()` | 统一入口：发现全部 SKILL.md |
| `agent/system_prompt.py` | `build_system_prompt_parts()` | 判定 has_skills_tools 后调索引构建 |
| `agent/skill_commands.py` | `_load_skill_payload()` | 运行时加载技能载荷 |
| `tools/skills_tool.py` | `skill_view()` | CLI/cron 两路径汇聚点 |
| `hermes_cli/main.py` | `cmd_chat()` | 启动同步 bundled 技能 |

---

### 六、发现/过滤关键函数

| 函数 | 位置 | 说明 |
|------|------|------|
| `iter_skill_index_files()` | `agent/skill_utils.py:797` | 统一入口，`os.walk(followlinks=True)` 穿透 symlink |
| `get_all_skills_dirs()` | `agent/skill_utils.py:515` | `~/.hermes/skills/` + external_dirs |
| `skill_matches_platform_list()` | `agent/skill_utils.py:175` | 平台兼容过滤 |
| `get_disabled_skill_names()` | `agent/skill_utils.py:369` | 禁用名单读取 |
| `_skill_should_show()` | `prompt_builder.py:1443` | 工具条件过滤 |

---

### 七、已知问题（from 图文件）

| Issue | 说明 |
|-------|------|
| #84667 | `skill_view` 的 `preprocess=True` 导致 cron 路径参数分叉 |
| #75130 | `skill_manager_tool` 用 `rglob` 漏 symlink 技能 → `iter_skill_index_files` 已统一修复 |

---

**总结**：Hermes 执行 `hermes` 命令时的 skill 加载分两条路——**启动注入**（索引层，让 agent 知道有哪些技能）和**运行时加载**（全文层，执行具体技能）。两者共享 `iter_skill_index_files()` 作为发现窄腰，但缓存策略不同。