# Issue 8：upstream #75130 — symlink 安装的 skill 对 skill_manage 不可见

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/75130
> 关联产出：`teach-7-skills-memory.md`（Skills 系统全景）
> 状态：第一推荐候选 · 无 PR 认领 · 修复点已在本地验证

---
    
## 一句话





```
tools/skill_manager_tool.py:659 和 :723 用 skills_dir.rglob("SKILL.md") 枚举技能。
pathlib.Path.rglob() 不进入目录 symlink → symlink 安装的 skill 对 skill_manage 不可见，
但 prompt 加载用的却是另一条遍历（能看见它们）。
```

| 遍历方式 | 找到的 SKILL.md |
|---|---|
| `rglob("SKILL.md")` | 393 |
| `os.walk(followlinks=True)` | 399 |
| **rglob 漏掉** | **6 个** |

| 漏掉的 skill | prompt 里可见 | rglob 可找到 |
|---|---|---|
| aionui-agent-team | ✅ | ❌ |
| orchestration | ✅ | ❌ |
| resource-escalation-ladder | ✅ | ❌ |
| orca-cli | ✅ | ❌ |
| computer-use | ✅ | ❌ |
| using-electronic-resources | ✅ | ❌ |

---

## 二、根因深挖：rglob 为什么不穿 symlink

### 直觉层

`symlink`（软链接）像一个"快捷方式"：`~/.hermes/skills/my-skill -> /opt/vendor/my-skill`。问题在于——快捷方式算不算"目录里的东西"？Python 的两个遍历器给了不同答案：

- `Path.rglob()` 保守：**不跟随** symlink，怕死循环（a → b → a）
- `os.walk(followlinks=True)` 激进：**跟随** symlink，同时靠 `visited` 集合防死循环

### 代码层

```python
# 现状（tools/skill_manager_tool.py:617）— 漏 symlink
for skill_md in skills_dir.rglob("SKILL.md"):   # 看不到软链目录
    ...

# 代码库其他模块 — 能穿透 agent/prompt_builder.py 
for skill_md in iter_skill_index_files(skills_dir, "SKILL.md"):
    # 内部就是 os.walk(skills_dir, followlinks=True)
```

### 为什么这是个 bug 而不是"特性"

关键在**两条遍历路径不一致**：prompt 构建（`agent/prompt_builder.py`）用 `iter_skill_index_files`（能看到 399 个），工具侧（`skill_manager_tool.py`）用 rglob（只看 393 个）。同一个技能，模型"看得见摸得着"，工具"看不见"。**不一致本身就是 bug**——而且这正好违反了 AGENTS.md 的宪法：行为契约要一致，不能两个子系统对同一份数据给出不同视图。

---

## 三、本地代码验证（我在 fork 上确认的）

### 漏网之鱼：只有 skill_manager_tool 还在裸用 rglob

```
tools/skill_manager_tool.py:617   _find_skill()                — skill_manage 按名找技能
tools/skill_manager_tool.py:681   _find_skill_in_other_profiles() — 跨 profile 查找
tools/skills_tool.py:1176         skill_view 的 Strategy 3    — 旧式扁平 <name>.md 查找（次要点）
```

其余所有 SKILL.md 发现路径**已经统一**在 `iter_skill_index_files`：

```
agent/skill_utils.py:797    iter_skill_index_files() — os.walk(followlinks=True) + 排除目录
agent/skill_commands.py:343 /skill 斜杠命令扫描
agent/prompt_builder.py:1576  prompt 构建（模型视图）
tools/skills_tool.py:721/1160  skills_list / skill_view
agent/skill_utils.py:709       其他工具函数
```

### 关键发现：正确实现已经存在于代码库

`agent/skill_utils.py:797`：

```python
def iter_skill_index_files(skills_dir: Path, filename: str):
    """Walk skills_dir yielding sorted paths matching *filename*..."""
    skills_dir_str = str(skills_dir)
    matches: list[str] = []
    for root, dirs, files in os.walk(skills_dir_str, followlinks=True):  # ← 穿透 symlink
        has_skill_md = "SKILL.md" in files
        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_SKILL_DIRS
            and not (has_skill_md and d in SKILL_SUPPORT_DIRS)
        ]
        if filename in files:
            matches.append(os.path.join(root, filename))
    for path in sorted(matches):
        yield Path(path)
```

所以这**不是"发明新轮子"，而是"把漏网的轮子换掉"**——修复即统一。

---

## 四、修复建议

### 推荐方案：统一到 iter_skill_index_files（★☆☆ 半小时级）

把 `tools/skill_manager_tool.py` 两个函数里的裸 rglob 替换成现成迭代器：

```python
# 617 行附近
from agent.skill_utils import get_all_skills_dirs, is_excluded_skill_path, iter_skill_index_files

def _find_skill(name: str) -> Optional[Dict[str, Any]]:
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in iter_skill_index_files(skills_dir, "SKILL.md"):
            if is_excluded_skill_path(skill_md):
                continue
            if skill_md.parent.name == name:
                return {"path": skill_md.parent}
    return None
```

同样的替换用在 `_find_skill_in_other_profiles()`（681 行）。

**为什么推荐它**：
1. **一行替换**，行为与代码库其他 6 处完全一致（Extend, don't duplicate——AGENTS.md 明文要求）
2. **白赚排除逻辑**：rglob 版本没有过滤 `EXCLUDED_SKILL_DIRS`（元数据/VCS/venv/cache 目录），`iter_skill_index_files` 自带了——顺带修掉一个潜在误匹配
3. `os.walk` 内部有 `visited` 去重，无死循环风险（rglob 的保守动机不成立）

### 备选方案：局部换 os.walk

不想动工具函数的话，直接在 `_find_skill` 里：

```python
for root, dirs, files in os.walk(skills_dir, followlinks=True):
    if "SKILL.md" in files and Path(root).name == name:
        return {"path": Path(root)}
```

但**不推荐**——会丢掉排序、排除逻辑，而且和代码库既有 API 分叉，下次又有人踩坑。

### 顺带项（可并入同一 PR）

- `skills_tool.py:1176` 的 `search_dir.rglob(f"{name}.md")`（旧式扁平文件回退查找）同样不穿 symlink——建议一并换成 `iter_skill_index_files(search_dir, f"{name}.md")`，保持整个 skills 域的发现路径 100% 一致
- 其余 `rglob("*")`（列文件清单用，如 `skills_tool.py:1331/1441`、`skill_commands.py:288`）影响的是 linked files 展示，非技能发现，可留待观察

### 测试思路

```python
# 1. 单元测试：构造 symlink 技能目录
#    tmp/skills/linked-skill -> tmp/real/linked-skill  (含 SKILL.md)
#    assert skill_manager_tool._find_skill("linked-skill") is not None   # 修复前 None，修复后命中

# 2. 回归：普通目录技能仍能找到（不破坏现有行为）
#    tmp/skills/normal-skill/SKILL.md → 仍命中

# 3. 防死循环：symlink 循环 a -> b -> a
#    iter_skill_index_files 不应挂死（os.walk 的 visited 保证）
```

### 风险与边界

| 风险 | 评估 |
|---|---|
| 行为变更 | 低——只是让工具侧视图对齐 prompt 侧视图 |
| 性能 | 可忽略——skills 目录规模几百级，os.walk 与 rglob 同量级 |
| 排除目录过滤 | 这是**增强**——rglob 版本来就不该扫 venv 目录 |
| 与其他 PR 撞车 | 已核查：**无 PR**（2026-07-31），作者只发了评论没提 PR |

---

## 五、关联知识（串起之前学的）

1. **teach-7 的"渐进披露"体系**：`skills_list`（tier1）→ `skill_view`（tier2）→ `skill_manage`（tier3）。本 issue 命中的正是 **tier3 的查找路径**——最深层级反而用了最原始的实现，越深越容易漏，这是"核心窄腰"原则下的常见代价。
2. **teach-5 的 cron/后台任务**：审批队列就是后台任务（`skills.write_approval`）的产物——一个没人审批的队列 8 天攒 357 条，生命周期管理缺失的问题在 teach-7 末尾的 curator 讨论里已经埋过伏笔。
3. **"统一入口"模式复读**：`iter_skill_index_files` 就像是 skills 域的"窄腰"——所有消费者都应从它拿文件清单，而不是各自写遍历。这跟 teach-3 的 `registry`、teach-4 的 `PluginContext`、teach-7 的 `MemoryProvider ABC` 是同一个设计哲学：**能力可以分散，入口必须收敛**。
4. **AGENTS.md 红线联动**：这个 bug 本质是"两个子系统对同一数据给出不一致视图"——在 Hermes 里，任何不一致最终都会以奇怪的用户可见行为暴露（技能改不动、队列积压、告警噪声）。

---

## 六、下一步选项

1. **动手修**：在 fork 上开分支，按推荐方案替换两处 rglob + 补单元测试 + 验证（预计 1 小时内完成初稿）
2. **先写 upstream 评论**：在 #75130 下补充"本地已验证 iter_skill_index_files 已存在、skill_manager_tool 是唯一漏网者"的发现（对作者有增量价值，可能加速官方修复）
3. **先讨论方案**：对替换范围（只修 617/681 还是连 1176 一起）有想法再定

你选哪个？😄

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/75130
