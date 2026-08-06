# teach-18：你 set 了一个数组，它却当字符串存了 —— 配置「类型契约」断裂拆解

> 教学读代码序列 · 衍生案例（walkthrough-1/2 的延伸）· 2026-08-06
> 素材来源：upstream issue #79270（已被 PR #79264 秒抢，fix(skills): validate external directory config）
> 涉及文件：`hermes_cli/config.py`（写入端）+ `agent/skill_utils.py`（读取端）

---

## 一、直觉：这就像"点菜时写了个备注，后厨却把备注当菜名"

想象你在餐厅点菜，菜单上写着"例汤：番茄蛋花汤 / 紫菜汤"。你怕服务员听岔，在订单上备注了一行：

```
例汤 = ["番茄蛋花汤", "紫菜汤"]     ← 你心想：两个都上
```

结果后厨把整行字（包括方括号和引号）当成**一个菜名**去查——查无此菜，于是**什么都不上**，而且也不告诉你，只在小票角落里写了个没人看的日志。

Hermes 的 `skills.external_dirs`（外部 skill 目录配置）就是这个"例汤"。用户想配置**多个**外部目录，用 JSON 数组格式输入：

```bash
hermes config set skills.external_dirs '["~/team-skills", "/shared/skills"]'
```

命令回显 `✓ Set skills.external_dirs = [...]`，看起来成功了。但运行时 `get_external_skills_dirs()` 返回**空列表**——你辛辛苦苦放的外部 skill 一个都没加载，而且全程静默。

**这就是本次要拆的 bug**：写入端把 JSON 数组字符串**原样落盘**成 YAML 标量，读取端又把整个字符串当成**一个目录**去检查，路径不存在 → 静默跳过。

---

## 二、动手：把整条链亲手走一遍

本地就能复现（用临时 HERMES_HOME，不碰真实配置）。我刚跑了一遍，结果如下：

```python
# 用户输入：JSON 数组字符串
'["/tmp/xxx/ext1", "/tmp/xxx/ext2"]'

# 写入端 coercion 后
'["/tmp/xxx/ext1", "/tmp/xxx/ext2"]'   # type: str —— 原样保留！

# 落盘后的 config.yaml
skills:
  external_dirs: '["/tmp/xxx/ext1", "/tmp/xxx/ext2"]'   # ← 注意引号：这是个字符串，不是列表

# 读取端
get_external_skills_dirs() → []        # 0 条！静默跳过

# 对照：手写 YAML 序列（正确格式）
skills:
  external_dirs:
    - /tmp/xxx/ext1
    - /tmp/xxx/ext2
get_external_skills_dirs() → [ext1, ext2]   # 2 条 ✅
```

**动手实验**（直接抄）：

```bash
cd /root/projects/hermes-agent-plus
# 1. 看写入端的 coercion 逻辑（只有 bool/int/float，没有 JSON 解析）
sed -n '8544,8558p' hermes_cli/config.py
# 2. 看读取端把 str 包成单元素的地方
sed -n '470,479p' agent/skill_utils.py
# 3. 看"目录不存在就静默跳过"的地方
sed -n '488,508p' agent/skill_utils.py
# 4. 看 DEFAULT_CONFIG 里这个键的声明（类型是 list！）
grep -n 'external_dirs' hermes_cli/config.py | head -3
```

---

## 三、为什么：写入端和读取端各自"宽容"，合起来就是 bug

拆开看，两端的行为**单独看都挺合理**：

**写入端**（`hermes_cli/config.py:8544-8558`）只做 best-effort coercion：字符串 `"true"/"off"` 转布尔、纯数字转 int/float，**其余一律原样存**。为什么这么设计？因为 `config set` 的输入永远是字符串（命令行参数），而配置值五花八门——枚举成员（`approvals.mode="off"`）绝对不能转成布尔，未知 key 保持原样最安全。代码注释写得很清楚（8544-8546 行）：*"Preserve values for string-typed settings... Unknown keys retain the historical best-effort coercion behavior."*

**读取端**（`agent/skill_utils.py:476-477`）看到 `str` 就包成单元素 `[raw_dirs]`。为什么？因为宽容——有人可能手写 `external_dirs: /path/to/dir`（单个字符串）也能用，没必要强制列表。这种"读取端容错"在配置系统里很常见。

**问题**：两端的宽容各自为政，中间没有一方负责"类型契约"。DEFAULT_CONFIG 里明明声明了 `"external_dirs": []`（`hermes_cli/config.py:2421`，list 类型），但：
- 写入端的 coercion 只看默认值**是不是 str**（`config.py:8548`），是 list 反而**什么都不做**（它的本意是"非字符串类型的 key 才尝试转换"，但对 list 类型它没有转换逻辑，JSON 数组字符串就这么漏过去了）；
- 读取端把整个 JSON 字符串当一个目录路径 → `expandvars`/`expanduser` 后 → `p.is_dir()` 为 False（`skill_utils.py:504`）→ `logger.debug(...)` 静默跳过（`skill_utils.py:508`）。

**有和没有的差别**：如果有类型契约，用户输入 JSON 数组字符串应该被解析成 list（或至少报错"格式不对"）。没有它，用户得到的是**看起来成功、实际零效果**——比报错更糟，因为排查方向完全错了（用户会去怀疑 skill 内容、目录权限，而不是配置格式）。

---

## 四、细节：三层代码，三个值得品的点

### 1. 写入端：`_default_value_for_key` 的存在本身就是个"类型锚"

```python
# hermes_cli/config.py:8481-8492
def _default_value_for_key(dotted_key: str):
    """Return the leaf value declared for *dotted_key* in ``DEFAULT_CONFIG``."""
    node = DEFAULT_CONFIG
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if not isinstance(node, dict) else None
```

这个函数的作用是：查 DEFAULT_CONFIG 里这个 key 的**声明类型**，coercion 决定要不要转换。但注意它的返回——`skills.external_dirs` 的默认值是 `[]`（list），而 coercion 的逻辑是：

```python
# hermes_cli/config.py:8547-8558
coerced_value: Any = value
if not isinstance(_default_value_for_key(key), str):   # list 不是 str → 进入转换分支
    if value.lower() in {'true', 'yes', 'on'}:
        coerced_value = True
    elif value.lower() in {'false', 'no', 'off'}:
        coerced_value = False
    elif value.isdigit():
        coerced_value = int(value)
    elif value.replace('.', '', 1).isdigit():
        coerced_value = float(value)
```

**坑点**：这个分支的**隐含假设**是"非字符串默认值的 key 只会收到标量输入"。它处理了 bool/int/float，但**没处理 list/dict**。对一个 list 类型的 key 传入 JSON 数组字符串，它就落在"四个 elif 全不中 → 保持原字符串"的默认路径上。而命令行输入又是字符串——所以 JSON 数组永远没机会变成 list。

### 2. 读取端：`isinstance(raw_dirs, str)` 的宽容变成了误导

```python
# agent/skill_utils.py:470-479
raw_dirs = skills_cfg.get("external_dirs")
if not raw_dirs:
    ...
if isinstance(raw_dirs, str):
    raw_dirs = [raw_dirs]      # 单个字符串 → 包成单元素列表
if not isinstance(raw_dirs, list):
    return []
```

这个分支的本意是支持 `external_dirs: /path` 这种手写单字符串。但它**不检查字符串里是不是 JSON 数组**——一个 `'["a","b"]'` 字符串被当成目录名 `["a","b"]`（带方括号引号的字面路径）去检查。之后：

```python
# agent/skill_utils.py:504-508
if p.is_dir():
    seen.add(p)
    result.append(p)
else:
    logger.debug("External skills dir does not exist, skipping: %s", p)   # ← 静默！
```

**坑点**：`debug` 级别的日志，用户根本看不到。错误被吞掉，表现为"配置了但没生效"。

### 3. 有趣的事实：DEFAULT_CONFIG 的注释里写了正确用法

```python
# hermes_cli/config.py:2421
"external_dirs": [],   # e.g. ["~/.agents/skills", "/shared/team-skills"]
```

注释里给的例子就是 JSON 数组语法——但那是 **YAML 文件里**的写法。用户照着这个例子用 `hermes config set` 命令输入，就踩坑了。**文档暗示的用法和 CLI 的实际行为不一致**，这是比代码 bug 更深一层的问题。

---

## 五、关联：这条链在你已经学过的模块里反复出现

1. **walkthrough-1/2（skill 加载链路）**：`get_external_skills_dirs()` 的返回值最终流向 `iter_skill_index_files()`（skill 索引遍历）——外部目录一个都没进索引，prompt_builder 里的 skill 列表自然就没有它们。**配置在加载链的最上游，错一格，全链静默**。

2. **teach-16（premise verification）**：这个 bug 的验证方法本身就是 premise verification——先用最小复现确认"现象真存在、根因在哪一行"，再判断修哪里。我们本地复现的结果（写入端原样落盘 + 读取端包单元素）和官方 PR #79264 的修复方向（validate external directory config）完全吻合。

3. **同类"类型契约"断裂案例**：还记得 teach-13 的 message-repair 吗？它是**消息格式**的契约（tool result 必须是合法结构），这次是**配置格式**的契约（list 类型的 key 收到字符串）。模式相同：**系统有两端（生产/消费），中间没有共享的 schema，一端改了另一端的隐含假设就崩**。

4. **静默失败**：`logger.debug` 级别的跳过日志是第三个坑。Hermes 其他地方（比如 skills_hub 的安全扫描）对失败都是显式报错——**"失败要响亮"** 是配置系统的普遍原则，这个案例是反面教材。

**思考题**：如果让你修，你会选哪个方案？
- A. 写入端：`config set` 对 list 类型的 key 尝试 `json.loads`；
- B. 读取端：`skill_utils` 遇 str 先尝试 `json.loads`；
- C. 两端都改，并加一条"配置格式校验"；
- D. 直接拒绝：list 类型的 key 在 CLI 里要求用多次 set 或明确报错。

提示：A 会影响所有 list 类型 key 的写入（比如 `custom_providers`），B 会让读取端更"魔法"（字符串碰巧是合法 JSON 就被解析，可能误伤），D 最保守但用户体验差。官方 PR #79264 选了 validate——你觉得它改的是哪端？为什么？

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/79270
