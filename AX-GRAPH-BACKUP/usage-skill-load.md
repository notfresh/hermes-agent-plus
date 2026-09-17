# 实战记录：如何用 X-GRAPH 找到 skill load 的源码

> 任务 0012 的实战用例。所有命令、输出、行号均为 2026-08-28 实测值。
> 图文件：`hermes-agent-plus/X-GRAPH/Layer-{1,2}-Graph.toml` + `Layer-3-Graph-skill_load.toml`
> 查询工具：`X-GRAPH/graph_query.py`

---

## 背景：为什么会有这张图

读 Hermes 源码（87 节点/163 边）时，传统方式（grep）的问题是：**命中一堆、没有语义、行号要自己猜**。X-GRAPH 把源码变成三层图——第一层源码分布、第二层 agent 隐式簇、第三层功能链——让"查功能 → 定位源码"变成两步操作。

## 目标

找到"skill load（技能加载）"这个功能的全部实现源码，并定位到函数级。

## 实战步骤

### 第一步：查功能链，拿到 16 个实现函数

```bash
cd /root/projects/hermes-agent-plus/X-GRAPH
python3 graph_query.py feature.skill-load
```

实测输出（节选）：

```
[REALIZED_BY] → func.agent.skill_commands._load_skill_payload   加载技能载荷（链路核心）
[REALIZED_BY] → func.agent.skill_commands.scan_skill_commands  扫描全部技能命令（发现阶段入口）
[REALIZED_BY] → func.agent.skill_utils.iter_skill_index_files  技能发现统一入口
[REALIZED_BY] → func.tools.skills_tool._parse_frontmatter      解析技能 frontmatter
[REALIZED_BY] → func.tools.skills_guard.scan_skill             安全检查
...（共 16 条，全部带 文件:行号 + 一句话职责）
```

一步拿到完整实现清单，且每个函数带语义标注。

### 第二步：识别五步链路

16 个函数不是平的，按图里的职责描述自然分成五步：

```
① 命令解析   resolve_skill_command_key(496) / scan_skill_commands(320)
② 技能发现   _find_all_skills(669) / iter_skill_index_files(797)
③ 载荷加载   _load_skill_payload(138) ← 心脏 / skill_view(961)
④ 预处理     preprocess_skill_content(128) / load_skills_config(25)
⑤ 安全检查   scan_skill(632) / should_allow_install(766)
```

（行号出处：Layer-3-Graph.toml 节点的 path 字段）

### 第三步：定位心脏，从图跳到源码

心脏是 `_load_skill_payload`，图中 path = `agent/skill_commands.py:138`：

```bash
sed -n '138,152p' /root/projects/hermes-agent-plus/agent/skill_commands.py
```

实测该处代码：

```python
def _load_skill_payload(skill_identifier: str, task_id: str | None = None) -> tuple[dict[str, Any], Path | None, str] | None:
    """Load a skill by name/path and return (loaded_payload, skill_dir, display_name)."""
    raw_identifier = (skill_identifier or "").strip()
    if not raw_identifier:
        return None
    try:
        from tools.skills_tool import SKILLS_DIR, skill_view
        from agent.skill_utils import normalize_skill_lookup_name
        normalized = normalize_skill_lookup_name(raw_identifier)
        loaded_skill = json.loads(
            skill_view(normalized, task_id=task_id, preprocess=False)
        )
```

行号准确：138 行就是函数定义，150-152 是真正的加载调用。

### 第四步：顺藤摸瓜——图上挂着的坑

查询 `feature.skill-load` 时，节点自带 `known_issues` 字段：

```
#84667 cron路径 skill_view preprocess 默认 True 导致加载失败（两路径参数分叉）
#75130 skill_manager_tool 用 rglob 漏 symlink 技能（iter_skill_index_files 已统一）
```

不用重新搜 issue——坑就在功能节点上。比如 #84667 的现场就在 `skill_commands.py:151` 的 `preprocess=False`（CLI 主动关）vs cron 路径不传（默认 True）。

### 第五步：钻取验证（可选）

```bash
python3 graph_query.py iter_skill_index_files   # 看发现入口挂在哪
python3 graph_query.py mod.agent -l 1           # 回到模块层看归属
python3 graph_query.py _load_skill_payload      # 模糊搜索直接命中
```

## 对比：无图 vs 有图

| | 无图（grep） | 有图（X-GRAPH） |
|---|---|---|
| 第一步 | 搜关键词，命中一堆（含 `_load_skill_ignore` 这类干扰项） | 查功能节点，16 个精准函数 |
| 第二步 | 逐个读文件判断哪些相关 | 自带语义（发现/加载/预处理/检查） |
| 第三步 | 自己数行号，还可能数错 | 行号当次核实，直接跳 |
| 坑位 | 不知道有哪些已知坑 | known_issues 挂在节点上 |

## 效果评估

**图定位源码的能力已全量审计**：87 个带 path 的节点全部有效（0 失效），16 个函数节点的行号全部验证通过（行号处确为 def/class）。

**当前能回答**：改 skill 加载要动哪些文件？每个文件里哪个函数是核心？已知坑在哪？
**当前不能回答**：函数间的调用顺序（CALLS 边未实测，待第三层二期）。

## 附录：命令速查

```bash
cd /root/projects/hermes-agent-plus/X-GRAPH
python3 graph_query.py feature.skill-load          # 功能 → 实现函数
python3 graph_query.py <关键词>                     # 模糊搜索节点
python3 graph_query.py <节点> -l 1                  # 只看第一层文件的关系
python3 graph_query.py <节点> -l core               # 只看 core 架构层
```
