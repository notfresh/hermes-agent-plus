# AX-GRAPH Schema 填写指南（手动增删节点/边用）

> 本文件是"编辑手册"：新增/修改/删除节点或边时照着填。
> 总纲参考：skill code-graph 的 `references/x-graph-schema.md`（关系语义、查询工具参数）。
> 写完必跑：`python3 graph_query.py --validate [-l N] [关键词]`
>
> `--validate` 范围控制：无参=全量 / `-l N`=只校验第 N 层文件 / 带关键词（或完整节点 id）=只校验匹配节点及其关联边。
> 分级：**Error（✗，exit≠0，必须修）**=悬空边 / path 不存在 / 行号非 def/class / function 缺 path / kind 非法 / 详情 key 悬空；**Warning（⚠，可暂缓）**=缺 layer / 缺 weight / 缺 desc 等历史欠账。

## 0. `layer-longlife` 元数据

`Layer-longlife.toml` 是项目级长期语义图。它和 Layer-1/2/3 一样由节点和边组成，但节点表达的是设计意图，而不是代码结构或运行时调用：

- `principle`：长期架构原则。
- `constraint`：实现时不能违反的限制。
- `decision`：已经做出的架构选择。
- `invariant`：重构后仍必须成立的系统性质。

### 0.1 长期层节点字段

| 字段 | TOML 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 全局唯一；长期层建议使用 `principle.*`、`constraint.*`、`decision.*`、`invariant.*` 前缀 |
| `kind` | string | 是 | 取值为 `principle`、`constraint`、`decision`、`invariant` |
| `path` | string | 是 | 规范来源路径，必须带实测行号，例如 `AGENTS.md:19` |
| `layer` | string | 是 | 使用现有架构层值：`core`、`capability`、`interface`、`application`、`entry`、`infra` |
| `source` | string | 否 | 来源文件和章节/行号，例如 `AGENTS.md:15-22` |
| `scope` | array of strings | 否 | 受影响的源码路径、节点 ID 或功能 ID |
| `status` | string | 否 | 生命周期状态，建议使用 `active`、`deprecated`、`proposed` |
| `desc` | string | 建议 | 一句话说明该长期语义 |
| `note` | string | 否 | 读码依据、适用边界或维护备注 |

`source` 是文档来源，`path` 是节点的主定位；`scope` 是声明式元数据，不替代 `GOVERNS` 等显式关系。数组使用 TOML 字符串数组，例如 `scope = ["file.run_agent", "file.model_tools"]`。

### 0.2 长期层边字段和关系

| 字段 | TOML 类型 | 必填 | 说明 |
|---|---|---|---|
| `from` | string | 是 | 起点节点 ID |
| `to` | string | 是 | 终点节点 ID |
| `rel` | string | 是 | 取值见下表 |
| `note` | string | 否 | 关系依据、适用范围或源码证据 |

长期层关系：

| `rel` | 方向 | 语义 |
|---|---|---|
| `IMPLIES` | 上层原则 → 约束/不变量 | 原则推出更具体的规则或性质 |
| `PROTECTS` | 原则/约束 → 不变量/功能 | 规范保护某个必须保持的性质或行为 |
| `GOVERNS` | 规范 → 模块/文件/功能/函数 | 规范约束该源码节点的设计或修改方式 |
| `JUSTIFIES` | 原则/证据 → 决策 | 原则或证据说明某项架构选择的原因 |
| `DERIVED_FROM` | 规范 → 来源节点 | 规范从另一个规范或上下文节点提取 |
| `CONFLICTS_WITH` | 规范/决策 ↔ 规范/决策 | 两个语义节点在同一适用范围内冲突 |

长期层关系不使用代码图专用的 `weight` 和 `at_line`：前者只表示 import 次数，后者只表示源码调用点行号。若需要源码证据，写入 `note` 或 `source`。

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
| `kind` | ✅ 必填 | 代码图取值：`module` / `file` / `cluster` / `subpackage` / `feature` / `function` / `constants` / `gitCommit`；长期层取值：`principle` / `constraint` / `decision` / `invariant` |
| `path` | ✅ 必填 | 相对仓库根路径。**function/constants 和长期层节点必须带 `:行号`**（如 `agent/skill_utils.py:27`、`AGENTS.md:19`）；file/module/cluster/subpackage/feature 不带 |
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
| `rel` | ✅ 必填 | 代码图取值：`CONTAINS` / `DEPENDS_ON` / `REALIZED_BY` / `CALLS` / `MODIFIES` / `ASSOCIATED_WITH`；长期层取值：`IMPLIES` / `PROTECTS` / `GOVERNS` / `JUSTIFIES` / `DERIVED_FROM` / `CONFLICTS_WITH` |
| `weight` | 条件必填 | **仅 `DEPENDS_ON`**：import 次数（静态实测） |
| `at_line` | 条件必填 | **仅 `CALLS`**：调用点行号（当次 grep 实测！）；长期层关系不使用 |
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
| `MODIFIES` | gitCommit → 提交直接修改的方法/测试 | 由该提交的 diff hunk 直接证明 | — |
| `ASSOCIATED_WITH` | gitCommit → 被修改方法依赖的关联方法 | 由当前源码调用或共享契约证明 | — |


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
