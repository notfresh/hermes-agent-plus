# AX-GRAPH Schema 填写指南（手动增删节点/边用）

> 本文件是"编辑手册"：新增/修改/删除节点或边时照着填。
> 总纲参考：skill code-graph 的 `references/x-graph-schema.md`（关系语义、查询工具参数）。
> 写完必跑：`python3 graph_query.py --validate [-l N] [关键词]`
>
> `--validate` 范围控制：无参=全量 / `-l N`=只校验第 N 层文件 / 带关键词（或完整节点 id）=只校验匹配节点及其关联边。
> 分级：**Error（✗，exit≠0，必须修）**=悬空边 / path 不存在 / 行号非 def/class / function 缺 path / kind 非法 / 详情 key 悬空；**Warning（⚠，可暂缓）**=缺 layer / 缺 weight / 缺 desc 等历史欠账。

## 8. 节点详细介绍（NodeDetails.toml）

- 独立 KV 文件（**不带 `Layer-` 前缀**，避免被 load() 合并进节点图）；key=节点 id，value=多行 markdown 读码笔记。
- 维护：`python3 graph_query.py -b <id>` 打开 $EDITOR（缺省 vim）编辑临时文件，保存退出自动写入；`--text` 直写；清空保存=删除该详情。
- 查询：`python3 graph_query.py <id> -d` 末尾显示。
- 校验：`--validate` 自动检查详情 key 必须是合法节点 id（悬空 = Error）。

---

## 1. 节点 [[nodes]] — 必填/可选

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ 必填 | 全局唯一。命名前缀表意（见 §3），重复定义会覆盖！ |
| `kind` | ✅ 必填 | 取值：`module` / `file` / `cluster` / `subpackage` / `feature` / `function` / `constants` |
| `path` | ✅ 必填 | 相对仓库根路径。**function/constants 必须带 `:行号`**（如 `agent/skill_utils.py:27`）；file/module/cluster/subpackage/feature 不带 |
| `layer` | ✅ 必填 | 取值：`core` / `capability` / `interface` / `application` / `entry` / `infra` |
| `desc` | ✅ 建议必填 | 一句话职责。查询工具展示全靠它，空 desc = 查询工具显示空白 |
| `note` | 可选 | 补充说明（跨文件引用、实测依据等） |
| `known_issues` | 可选 | 仅 feature 常用：issue 编号 + 一句话坑 |
| `expanded` | 可选 | 仅 cluster：`true`/`false`（**必须小写**，`True` 解析失败） |

## 2. 边 [[edges]] — 必填/可选

| 字段 | 必填 | 说明 |
|---|---|---|
| `from` | ✅ 必填 | 起点节点 id |
| `to` | ✅ 必填 | 终点节点 id |
| `rel` | ✅ 必填 | 取值：`CONTAINS` / `DEPENDS_ON` / `REALIZED_BY` / `CALLS` |
| `weight` | 条件必填 | **仅 `DEPENDS_ON`**：import 次数（静态实测） |
| `at_line` | 条件必填 | **仅 `CALLS`**：调用点行号（当次 grep 实测！） |
| `note` | 可选 | 实测依据 / 补充说明 |

## 3. id 命名规则

| 前缀 | 规则 | 示例 |
|---|---|---|
| `func.` | `<路径去扩展名>.<函数名>` | `func.agent.skill_utils.iter_skill_index_files` |
| `func.`（类） | 类节点用类名 | `func.tools.skills_hub.SkillMeta` |
| `file.` | `<模块>.<文件名>`（点分割） | `file.hermes_cli.main`、`file.agent.system_prompt` |
| `const.` | `<路径去扩展名>.<常量名>` | `const.agent.skill_utils.EXCLUDED_SKILL_DIRS` |
| `feature.` | `<功能名>`（第三层每功能一文件） | `feature.skill-startup` |
| `mod.` | 模块 | `mod.agent` |
| `cluster.` | `<模块>.<簇名>`（第二层） | `cluster.agent.adapters` |

## 4. 边语义（选哪条）

| rel | 语义 | 判据 | 必备字段 |
|---|---|---|---|
| `CONTAINS` | 归属（大包小） | mod→file→func，方向单向 | — |
| `DEPENDS_ON` | import 耦合 | 模块/簇级；weight=import 次数实测 | `weight` |
| `REALIZED_BY` | feature → 实现函数 | 想研究这功能从这里读起 | — |
| `CALLS` | 函数 → 函数（执行顺序） | at_line=调用点行号实测 | `at_line` |

CONTAINS 建边三问：①B 是 A 的组成部分（不是"用到"）②去掉边 B 仍独立存在 ③方向大包小。
不建：平级文件之间（那是 DEPENDS_ON）、跨层粒度（函数↔文件）、跨模块复用。

## 5. 铁律

1. **行号当次 grep 实测**——源码更新会漂移（skill_commands.py 的 `_load_skill_payload` 725→138），不能凭记忆/旧文档
2. **关系实测不编造**——测不了标 `note = "待验证"`，不能硬写
3. **已有节点跨文件引用，不重复定义**——`func.agent.skill_utils.iter_skill_index_files` 定义在 skill_load 图，skill_startup 图直接引用；重复定义 = 后加载的覆盖先加载的（id 冲突）
4. 新增后必跑校验：`python3 graph_query.py --validate [-l N] [关键词]`

## 6. 完整示例：加一个函数 + 边

假设给 `agent/foo.py` 的新函数 `bar`（行号 42，当次 grep 实测）建图：

```toml
# ── 挂在 Layer-3-Graph-<你的功能>.toml ──

[[nodes]]  # 节点 func.agent.foo.bar: 职责一句话
id = "func.agent.foo.bar"
kind = "function"
path = "agent/foo.py:42"
layer = "core"
desc = "做了什么，一句话说清"

# 归属边（若 file.agent.foo 节点已存在则直接引用，不重复建）
[[edges]]
from = "file.agent.foo"
to = "func.agent.foo.bar"
rel = "CONTAINS"

# 调用边（at_line = bar 里调用 baz 的行号，grep 实测）
[[edges]]
at_line = 88
from = "func.agent.foo.bar"
to = "func.agent.foo.baz"
rel = "CALLS"

# 功能归属（若该函数实现了某个 feature）
[[edges]]
from = "feature.your-feature"
to = "func.agent.foo.bar"
rel = "REALIZED_BY"
```

## 7. 删除注意事项

1. 删节点前先查它的边：`python3 graph_query.py <id>`（出边 + 入边一起列出）
2. **被跨文件引用的节点**（如 `iter_skill_index_files` 被 skill_load + skill_startup 两图引用）——删除前搜全图：`grep -r "<id>" Layer-*.toml`
3. 删 feature 节点时连带它的 REALIZED_BY 边；删 file 节点时连带它的 CONTAINS 边（子函数节点如无人引用一并删）
