# 走读卡 2：Skill 的 frontmatter 是怎么被解析的？凭什么"显示/不显示"？

> 教学读代码序列 · 第 2 份 · 2026-08-05
> 配套：走读卡 1（skill 加载链路）→ 本卡深入"解析 + 过滤"环节
> 代码版本：hermes-agent-plus（本地 fork）
> **本卡所有代码都标注了 文件:行号，请打开对应源码对照着读**

---

## 一、现象入口

你打开 `~/.hermes/skills/ragagent-quiz/SKILL.md`，开头是：

```yaml
---
name: ragagent-quiz
description: RAG Agent 面试备考刷题 Skill
languages: ["zh-CN"]
tags: ["rag", "agent", "quiz"]
---
```

问题：这段 `---` 夹着的 YAML 是怎么变成 dict 的？为什么有的技能在系统提示词里能看到、有的看不到？

## 二、调用路径图（带精确位置）

```
build_skills_system_prompt()                       agent/prompt_builder.py:1490
   │  ① 内存缓存 _SKILLS_PROMPT_CACHE                agent/prompt_builder.py:1535
   │  ② 磁盘快照 .skills_snapshot.json               agent/prompt_builder.py:1542
   │  ③ 冷路径全盘扫描：
   │
   ├── iter_skill_index_files()                      agent/skill_utils.py:797
   │        os.walk(followlinks=True) → 所有 SKILL.md 路径
   │
   ├── _parse_skill_file(skill_file)                 agent/prompt_builder.py:1417
   │        │  ├── parse_frontmatter(raw)            agent/skill_utils.py:123
   │        │  │        YAML → dict（含 BOM 处理）
   │        │  ├── skill_matches_platform(fm)        agent/skill_utils.py:200
   │        │  │        platforms: 字段 → OS 匹配
   │        │  ├── skill_matches_environment(fm)     agent/skill_utils.py:284
   │        │  │        environments: 字段 → 运行时环境匹配
   │        │  └── extract_skill_description(fm)     （同文件附近）
   │        └── 返回 (is_compatible, frontmatter, description)
   │
   ├── extract_skill_conditions(frontmatter)         agent/skill_utils.py:614
   │        metadata.hermes.* → 条件字段
   │
   └── _skill_should_show(conditions, tools, toolsets)  agent/prompt_builder.py:1443
            fallback_for / requires → 是否隐藏
```

## 三、逐段精读（每段标注位置，请对照源码）

### 段 1：解析入口 — parse_frontmatter()（agent/skill_utils.py:123-169）

```python
if content.startswith("\ufeff"):          # :143  BOM 处理
    content = content[1:]
if not content.startswith("---"):         # :147  没有 --- 开头 = 无 frontmatter
    return frontmatter, body

end_match = re.search(r"\n---\s*\n", content[3:])   # :150  找结束符
yaml_content = content[3 : end_match.start() + 3]   # :154  截出 YAML 区

try:
    parsed = yaml_load(yaml_content)      # :158  CSafeLoader 完整 YAML
    if isinstance(parsed, dict):
        frontmatter = parsed
except Exception:
    # :161-167  fallback：简单 key:value 拆行
    for line in yaml_content.strip().split("\n"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
```

大白话，三个细节：
- **BOM 处理（:143）**：Windows 记事本存 UTF-8 会在开头塞一个 `\ufeff`（零宽字符），不剥掉的话 `startswith("---")` 永远为 False，整个 frontmatter 静默丢失——name、description、platforms 全没了。这是踩过坑才加的防御。
- **正则找结束符（:150）**：`\n---\s*\n` 匹配换行 + `---` + 可选空白 + 换行。注意它从 `content[3:]` 开始找，跳过开头的 `---`。
- **try/except 双轨（:157-167）**：YAML 解析失败不报错，退回最简单粗暴的 `key: value` 逐行拆分。宁可解析得粗糙，也不让整个技能加载失败。

### 段 2：平台门 — skill_matches_platform_list()（agent/skill_utils.py:175-197）

```python
def skill_matches_platform_list(platforms: Any) -> bool:
    if not platforms:
        return True                    # :177-178  没写 = 全平台兼容
    if not isinstance(platforms, list):
        platforms = [platforms]
    current = sys.platform             # :181  "linux" / "darwin" / "win32"
    running_in_termux = is_termux()
    for platform in platforms:
        normalized = str(platform).lower().strip()
        mapped = PLATFORM_MAP.get(normalized, normalized)
        if current.startswith(mapped): # :186  前缀匹配
            return True
        if running_in_termux and mapped == "linux":  # :192
            return True
        if running_in_termux and mapped in ("termux", "android"):  # :195
            return True
    return False
```

大白话：
- **没写 platforms = 全兼容（:177）**：向后兼容的默认值。老技能没有这个字段，不能被静默隐藏。
- **前缀匹配（:186）**：`current.startswith(mapped)` 而不是 `==`——`sys.platform` 可能是 `"linux"`、`"linux2"`、`"darwin"`（macOS 的 sys.platform 就是 darwin，不是 macos），所以 frontmatter 里写 `platforms: [macos]` 时，`PLATFORM_MAP` 会把 `macos` 映射成 `darwin` 再匹配。
- **Termux 特判（:192-195）**：Android 上的 Termux 里 `sys.platform` 在 Python 3.13 前是 `"linux"`、之后变 `"android"`，所以 `linux` 标签和 `termux`/`android` 标签都要认。

### 段 3：环境门 — skill_matches_environment()（agent/skill_utils.py:284-309）

```python
environments = frontmatter.get("environments")
if not environments:
    return True                        # :307-308  没写 = 任何环境都相关

for env in environments:               # OR 语义：任一匹配即可
    if _detect_environment(env):       # :238  实际探测
        return True
return False
```

配合 `_detect_environment()`（agent/skill_utils.py:238-281）看关键几行：

```python
if env == "kanban":
    if os.getenv("HERMES_KANBAN_TASK") or os.getenv("HERMES_KANBAN_BOARD"):
        result = True                  # :255-256  看环境变量
    else:
        from tools.kanban_tools import _profile_has_kanban_toolset
        result = bool(_profile_has_kanban_toolset())   # :261  看 profile 配置
elif env == "docker":
    result = is_container()            # :268
elif env == "s6":
    result = os.path.isdir("/run/s6") or os.path.isdir("/package/admin/s6-overlay")
                                       # :276-277  看文件系统标记
```

大白话：
- **环境的探测 = 看环境变量 + 看文件系统 + 看配置**，不同环境用不同信号：kanban 看 env var/profile 工具集、docker 看是否容器、s6 看 /run/s6 目录存不存在。
- **缓存（:244, :280）**：`_ENV_DETECT_CACHE` 进程内只探测一次——环境不会在进程运行中变化，每次扫描都重新探测纯属浪费。
- ⚠️ 关键设计：这是 **offer-time（展示时）** 过滤。`skill_view` 显式加载**不受这个门限制**——"显式请求 = 显式同意"（:296-301 注释）。

### 段 4：条件激活 — extract_skill_conditions() + _skill_should_show()

```python
# agent/skill_utils.py:614-628
def extract_skill_conditions(frontmatter):
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}                  # :618  畸形 YAML 防御
    hermes = metadata.get("hermes") or {}
    if not isinstance(hermes, dict):
        hermes = {}
    return {
        "fallback_for_toolsets": hermes.get("fallback_for_toolsets", []),
        "requires_toolsets": hermes.get("requires_toolsets", []),
        "fallback_for_tools": hermes.get("fallback_for_tools", []),
        "requires_tools": hermes.get("requires_tools", []),
    }
```

```python
# agent/prompt_builder.py:1443-1471
def _skill_should_show(conditions, available_tools, available_toolsets):
    if available_tools is None and available_toolsets is None:
        return True                    # :1449-1450  无过滤信息 = 全显示
    at = available_tools or set()
    ats = available_toolsets or set()

    # fallback_for: 主工具在场 → 隐藏自己（我是备胎）
    for ts in conditions.get("fallback_for_toolsets", []):
        if ts in ats:
            return False
    for t in conditions.get("fallback_for_tools", []):
        if t in at:
            return False

    # requires: 必需工具缺席 → 隐藏自己
    for ts in conditions.get("requires_toolsets", []):
        if ts not in ats:
            return False
    for t in conditions.get("requires_tools", []):
        if t not in at:
            return False
    return True
```

大白话，这是整套机制的"决策层"：
- **四类条件，两类语义**：`fallback_for_*` = "XX 在场我就退场"（备胎逻辑）；`requires_*` = "没有 XX 我就不上场"（依赖逻辑）。
- **双层防御（:1449）**：调用方没传工具信息时，一律显示——宁可多显示不可漏显示，向后兼容。
- **条件藏在 metadata.hermes 下（:616-622）**：frontmatter 里长这样：

```yaml
metadata:
  hermes:
    requires_toolsets: [web]      # 没有 web 工具集就不显示
    fallback_for_tools: [web_search]  # 有 web_search 主工具就隐藏
```

## 四、动手实验（3 分钟，本地可做）

```bash
cd /root/projects/hermes-agent-plus

# 1. 实际解析一个技能文件，看 frontmatter 长啥样
python3 -c "
from agent.skill_utils import parse_frontmatter, extract_skill_conditions
fm, body = parse_frontmatter(open('/root/.hermes/skills/ragagent-quiz/SKILL.md', encoding='utf-8').read())
print('frontmatter keys:', list(fm.keys()))
print('conditions:', extract_skill_conditions(fm))
"

# 2. 看 _skill_should_show 怎么过滤（模拟有/无 web 工具集）
python3 -c "
from agent.prompt_builder import _skill_should_show
c = {'requires_toolsets': ['web'], 'fallback_for_toolsets': [], 'requires_tools': [], 'fallback_for_tools': []}
print('有 web 工具集 →', _skill_should_show(c, None, {'web'}))
print('无 web 工具集 →', _skill_should_show(c, None, {'file'}))
"

# 3. 对比走读卡1的实验：rglob vs walk 找到的技能数
python3 -c "
from agent.skill_utils import iter_skill_index_files, get_skills_dir
print('walk 扫描到', len(list(iter_skill_index_files(get_skills_dir(), 'SKILL.md'))), '个技能')
"
```

## 五、思考题（3 道，答完我批）

1. **复述题**：一个 SKILL.md 从读到决定"显示/不显示"，依次经过哪 4 道关卡？（提示：BOM→平台→环境→条件）
2. **预测题**：如果某个技能 frontmatter 写了 `platforms: [win32]`，而当前系统是 Linux，`_parse_skill_file` 会返回什么？它在系统提示词里会出现吗？`skill_view` 还能强制加载吗？（提示：看 :1427 和 :296-301 的注释）
3. **追问题**：`fallback_for_toolsets` 和 `requires_toolsets` 都在 `metadata.hermes` 下，为什么设计者要把它们藏在两层嵌套里而不是平铺在顶层？想想跟 AGENTS.md 里"贡献准则"哪条有关？（提示：想想 frontmatter 的命名空间）

---

下一条预告：tool/toolset 系统的加载与注册（available_tools / available_toolsets 到底是怎么收集的——那是 _skill_should_show 的输入来源）。读完这张卡、做完实验，回我结果或卡点，明天出第 3 份。
