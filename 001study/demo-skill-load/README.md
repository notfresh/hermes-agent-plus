# Skill 加载流程 Demo（001study/skill-load-demo）

演示 Hermes 在每轮对话开始（系统提示构建）时 Skill 的加载过程。
纯标准库，不依赖 Hermes 本体，跑自己的临时 skills 目录。

```bash
python3 skill_load_demo.py
```

## 一、真实调用链（源码位置）

每轮对话开始时，系统提示里会注入一份 skill 索引（名字 + 描述，不是全文），
模型看到索引后按需调 `skill_view` 加载全文。完整链路：

```
AIAgent._build_system_prompt_parts()          run_agent.py:3810
 └─ build_system_prompt_parts(agent)          agent/system_prompt.py:147
     └─ build_skills_system_prompt(...)       agent/prompt_builder.py:1490
         ├─ Layer 1: 进程内 LRU 缓存          prompt_builder.py:1521
         │    key = (skills_dir, external_dirs, tools, toolsets,
         │          platform, disabled, compact_categories)
         ├─ Layer 2: 磁盘快照                 prompt_builder.py:1346 _load_skills_snapshot
         │    .skills_prompt_snapshot.json + mtime/size manifest
         └─ Layer 3: 全量文件系统扫描          skill_utils.py:796 iter_skill_index_files
              │    os.walk(followlinks=True) —— 会跟 symlink
              ├─ 解析 SKILL.md frontmatter    prompt_builder.py:1417 _parse_skill_file
              │    (平台过滤 + 环境过滤 + 描述提取)
              ├─ 快照条目构建                 prompt_builder.py:1383 _build_snapshot_entry
              ├─ 条件过滤                     prompt_builder.py:1443 _skill_should_show
              │    (requires_toolsets / fallback_for_toolsets)
              └─ 渲染 available_skills 段     prompt_builder.py:1692-1742
模型按需加载全文:
 └─ skill_view(name)                         tools/skills_tool.py:961
     └─ _find_skill(name)                    tools/skill_manager_tool.py:605
          rglob("SKILL.md") —— 不跟 symlink (#75130 的坑)
```

## 二、三层缓存 = 性能核心

索引内容取决于 (skills 目录, 可用工具, 可用 toolsets, 平台, 禁用列表)。
每次对话都重扫磁盘太贵，于是：

| 层 | 生命周期 | 命中条件 | demo 场景 |
|----|----------|----------|-----------|
| L1 LRU | 进程内 | 同一进程内 key 相同 | 第 2 次构建，零磁盘 |
| L2 快照 | 跨进程（磁盘） | manifest（mtime+size）未变 | 第 3 次构建（新会话），不重扫 |
| L3 全扫 | 每次失效 | 前两层都 miss | 第 1 次冷启动 / 第 4 次改文件后 |

demo 里 `scan_count` 全程只涨到 2：冷启动 1 次 + 改文件后 1 次。
这就是"每次对话都有 skill 索引、但不用每次都重扫磁盘"的秘密。

## 三、过滤规则（索引里"看不到"的 skill）

1. **平台过滤**（prompt_builder.py:1427）— `platforms: [windows]` 在 Linux 上隐藏
2. **环境过滤**（prompt_builder.py:1434）— 运行时环境不匹配的隐藏（如 kanban-only skill 对非 kanban 用户）
3. **禁用列表**（get_disabled_skill_names）— `hermes skills config` 关闭的
4. **条件过滤**（prompt_builder.py:1443）— requires_toolsets 不在场 / fallback_for 在场 → 隐藏
   （隐藏只在"索引展示"层；显式 skill_view 永远能加载）

## 四、彩蛋：issue #75130（你保留关注的那个）

同一个项目里两种遍历方式，行为不同：

| 位置 | 遍历方式 | symlink 目录 |
|------|----------|--------------|
| 索引扫描 `skill_utils.py:796` | `os.walk(followlinks=True)` | ✅ 能跟 |
| 按名查找 `skill_manager_tool.py:617` | `Path.rglob("SKILL.md")` | ❌ 跟不了 |

结果：symlink 安装的 skill **显示在索引里**（模型以为它有），但模型调
`skill_view` 时 `_find_skill` 用 rglob **找不到** → "索引里有、加载时消失"。
demo 末尾用真实行为对比复现了这一点。

## 五、怎么继续玩

```python
# 换 toolsets 看条件过滤变化 (terminal-demo 需要 terminal)
python3 -c "
import sys; sys.path.insert(0, '.')
from skill_load_demo import *
# ... 或直接改 demo 里 build({'terminal'}) 为 build(set())
"
```

思考题：为什么 `_parse_skill_file` 出错时返回 `(True, {}, "")`（宁可显示
也不隐藏）？提示：想想一个损坏的 SKILL.md 应该让 skill 消失，还是让模型
能通过 skill_view 看到原始报错？
