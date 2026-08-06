# 走读卡 1：Skill 加载链路 — 你问 Hermes 时，技能清单是哪来的？

> 教学读代码序列 · 第 1 份 · 2026-08-04
> 配套概念：teach-7-skills-memory.md（概念层）→ 本卡（代码层）
> 代码版本：hermes-agent-plus（本地 fork）

---

## 一、现象入口

你每次开对话，系统提示词里都有一大段「可用技能列表」——就是它让 agent 知道"我有 ragagent-quiz 这个技能、大概能干嘛"。

问题：这段列表是怎么从磁盘上的技能文件夹，变成提示词里的文字的？

## 二、调用路径图（全链路）

```
agent 启动/构建提示词
   │
   ▼
agent/prompt_builder.py  _build_skills_prompt()
   │  ① 查内存缓存 _SKILLS_PROMPT_CACHE（同一个会话只算一次）
   │  ② 没缓存 → 读磁盘快照 .skills_snapshot.json
   │  ③ 没快照 → 全盘扫描（cold path）
   │
   ├── agent/skill_utils.py  iter_skill_index_files()  ← 真正的"找文件"
   │        os.walk(followlinks=True) 排除目录 → 产出所有 SKILL.md 路径
   │
   ├── 逐个 _parse_skill_file() 解析 frontmatter（name/description/tags...）
   │
   ▼
  技能名 + 描述 按 category 分组 → 写进系统提示词
```

另一条支路（用户说"skill_view xxx"时）：

```
tools/skills_tool.py / skill_manager_tool.py
   │
   ▼
tools/skill_manager_tool.py:605  _find_skill(name)
   │      get_all_skills_dirs() → 每个目录 rglob("SKILL.md") → 目录名匹配
   ▼
返回 skill 目录路径 → 读 SKILL.md 全文
```

## 三、逐段精读（核心 3 段）

### 段 1：入口 — 有缓存走缓存，没缓存扫盘（prompt_builder.py:1535-1542）

```python
with _SKILLS_PROMPT_CACHE_LOCK:
    cached = _SKILLS_PROMPT_CACHE.get(cache_key)
    if cached is not None:
        _SKILLS_PROMPT_CACHE.move_to_end(cache_key)
        return cached          # ← 同一会话里技能列表只算一次

# ── Layer 2: disk snapshot ────────────────────
snapshot = _load_skills_snapshot(skills_dir)
```

大白话：**提示词构建有三级缓存——内存缓存 → 磁盘快照 → 全盘扫描**。
为什么？因为扫盘很贵（几百个技能文件 + 解析 frontmatter），一个长会话里系统提示词会重建很多次（换工具、压缩上下文），每次都扫盘就太慢了。

### 段 2：真正找文件 — iter_skill_index_files()（skill_utils.py:797-819）

```python
def iter_skill_index_files(skills_dir: Path, filename: str):
    skills_dir_str = str(skills_dir)
    matches: list[str] = []
    for root, dirs, files in os.walk(skills_dir_str, followlinks=True):
        has_skill_md = "SKILL.md" in files
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDED_SKILL_DIRS
                   and not (has_skill_md and d in SKILL_SUPPORT_DIRS)]
        if filename in files:
            matches.append(os.path.join(root, filename))
    for path in sorted(matches):
        yield Path(path)
```

大白话，三个细节：
- `os.walk(followlinks=True)` — **穿透 symlink**。技能可以装在别的目录、软链过来，得能找到。
- `dirs[:] = [...]` — 原地裁剪要往下走的子目录：排除 `EXCLUDED_SKILL_DIRS`（缓存、.git、venv 等）；如果一个目录已经有 SKILL.md 了，就不进它的 references/templates 子目录翻（那些是渐进式加载的数据，不是技能根）。
- `sorted()` — 保证顺序稳定，不然每次扫盘技能列表顺序乱跳，提示词缓存就失效了。

### 段 3：按名查找 — _find_skill()（skill_manager_tool.py:605-622）

```python
def _find_skill(name: str) -> Optional[Dict[str, Any]]:
    from agent.skill_utils import get_all_skills_dirs, is_excluded_skill_path
    for skills_dir in get_all_skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            if is_excluded_skill_path(skill_md):
                continue
            if skill_md.parent.name == name:   # ← 按"目录名"匹配
                return {"path": skill_md.parent}
    return None
```

大白话：用户让 agent "查看 skill X"时，agent 按**目录名**找（`~/.hermes/skills/ragagent-quiz/SKILL.md` → 目录名 `ragagent-quiz`）。

⚠️ 这里就是 issue #75130 的现场：`rglob()` **不穿透 symlink**，而上面 `iter_skill_index_files()` 用的是 `os.walk(followlinks=True)` 会穿透——两个入口对同一套技能文件的发现能力不一致，技能通过 symlink 安装时，一个能看到、一个看不到。这正是"读代码发现 bug"的经典例子。

## 四、动手实验（3 分钟，本地可做）

```bash
cd /root/projects/hermes-agent-plus

# 1. 看当前技能目录长啥样
ls ~/.hermes/skills/ | head

# 2. 模拟 _find_skill 的 rglob：看能不能找到 symlink 装的技能
python3 -c "
from pathlib import Path
hits = list(Path('/root/.hermes/skills').rglob('SKILL.md'))
print('rglob 找到', len(hits), '个')
print('前 3 个:', [str(h) for h in hits[:3]])
"

# 3. 再看 iter_skill_index_files 的 walk 版本（应该能多找到一些）
python3 -c "
from agent.skill_utils import iter_skill_index_files, get_skills_dir
hits = list(iter_skill_index_files(get_skills_dir(), 'SKILL.md'))
print('walk 找到', len(hits), '个')
print('前 3 个:', [str(h) for h in hits[:3]])
"
```

观察：两行命令的计数是否一样？不一样的话，多出来的那些就是 symlink 装的技能——#75130 的 bug 现场。

## 五、思考题（3 道，答完我批）

1. **复述题**：技能列表从磁盘到系统提示词，经过了哪三级缓存？每级失效条件是什么？
2. **预测题**：如果我在 `~/.hermes/skills/` 下新建一个 `my-test/SKILL.md`，`_find_skill("my-test")` 会找到吗？`iter_skill_index_files()` 呢？两个都会吗？
3. **追问题**：`_find_skill` 用 `parent.name == name` 匹配，`iter_skill_index_files` 却只看文件名——为什么 prompt 构建不需要知道技能名也能工作？提示：想想系统提示词里那段列表是按什么组织的（回头看段 1 的分组逻辑）。

---

下一条预告：skill 的 frontmatter 是怎么被解析、`_skill_should_show()` 怎么决定"这个技能这场景显不显示"。读完这张卡、做完实验，回我结果或卡点，明天出第 2 份。
