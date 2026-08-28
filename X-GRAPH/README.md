# X-GRAPH — Hermes Agent 源码图

> 任务 0012 的产物：用图理解 Hermes 源码分布、功能实现路径、方便迁移。
> 任务档案（背景/成果/计划）：`~/.hermes/knowledge/x-graph/README.md`

## 目录结构

```
X-GRAPH/
├── Layer-1-Graph.toml    第一层：源码级分布（模块 + 顶层文件 + cron 文件）
├── Layer-2-Graph.toml    第二层：agent 模块隐式簇展开
├── Layer-3-Graph-skill_load.toml  第三层：功能级（feature.skill-load 功能链，1 feature + 6 file + 15 function）
├── graph_query.py        查询工具（自动合并所有 Layer-*.toml）
└── README.md             本文件
```

## 数据模型（TOML schema）

```toml
[graph]          # 图元信息：name / layer / granularity / created / schema / note
[[nodes]]        # 实体
  id            # 唯一标识，命名：mod.xxx / file.xxx / cluster.xxx / file.agent.xxx
  kind          # module | file | cluster(隐式簇) | subpackage
  path          # 源码路径
  layer         # 架构分层（见下）
  files/lines   # 规模（代码文件数/行数）
  desc          # 一句话职责
  expanded      # 是否已展开到下一层
[[edges]]        # 关系
  from / to     # 节点 id（跨文件引用合法，查询时合并校验）
  rel           # CONTAINS | DEPENDS_ON
  weight        # 仅 DEPENDS_ON：import 次数
  note          # 补充说明
```

## 边定义

### CONTAINS（内聚结构）
- 语义：**A 包含/组成 B**（归属，单向，容器在前）
- 三种场景：目录→文件（真实归属）、模块→簇（逻辑归属）、簇→成员（逻辑分组）
- 判据：①B 是 A 的组成部分（不是"用到"）②去掉边 B 仍独立存在（包含≠依赖）③方向大包小
- 不建：平级文件之间（那是 DEPENDS_ON）、跨层粒度（函数↔文件）、跨模块复用

### DEPENDS_ON（耦合）
- 语义：**A 依赖 B**（A 的代码 import 了 B）
- weight = import 语句累计次数，衡量耦合强度
- 与 CONTAINS 区别：CONTAINS 回答"它属于谁"（静态归属）；DEPENDS_ON 回答"它用到谁"（依赖行为）

## weight 统计口径（重要）

第一层模块级 DEPENDS_ON = **Python 静态 import 计数**：
- 扫描模块内所有 .py 的 import 行（`import x` / `from x import y`），目标为顶层模块即计数
- 方向：谁 import 谁，边指向谁；weight = 模块内全部文件加总

**四条限定（诚实声明）：**
1. **静态非运行**：只数 import 语句，不追踪运行时是否真调用；动态导入（importlib）可能漏
2. **仅 Python**：前端应用（apps/ui-tui/web）与后端走 IPC/API 协议，不走 import，故无 DEPENDS_ON 边（待验证后补 CONNECTS 类边）
3. **模块级是聚合**：看不出具体文件，文件级依赖看第二层
4. **相对导入（from . import）在模块级不计**：属模块内部依赖，第二层分析时才有意义

## 架构分层（layer 属性）

| layer | 含义 | 节点示例 |
|---|---|---|
| core | 核心簇（被广泛依赖的底座） | hermes_cli / agent / tools |
| capability | 能力层（可插拔扩展） | plugins / cron / providers |
| interface | 平台接口 | gateway / tui_gateway / acp_adapter |
| application | 前端应用 | apps / ui-tui / web |
| entry | 进程入口 | cli.py / run_agent.py |
| infra | 基础设施 | hermes_constants / utils.py |

## 查询工具

```bash
python3 graph_query.py <节点id或关键词> [-l 过滤]
python3 graph_query.py                          # 缺参：列出可查节点
python3 graph_query.py mod.agent                # 全层合并查询
python3 graph_query.py mod.agent -l 1           # 文件层过滤（只看第一层）
python3 graph_query.py mod.agent -l core        # 架构层过滤（只看 core 层）
```

特性：模糊匹配（精确→包含→近似）、缺参自动提示、跨文件引用自动合并。

## 更新规范

1. 加节点：`[[nodes]]` 块，注释与 `[[nodes]]` 同行（折叠可读），id 前缀表明 kind
2. 加边：`[[edges]]` 块；DEPENDS_ON 必须给 weight（实测），无法实测的标 note="待验证"
3. **铁律：关系必须实测，不编造**
4. 每层独立文件 Layer-N-Graph.toml，跨文件引用合法（查询工具自动合并）
5. 布尔值 TOML 必须小写 true/false（教训：Python repr 会输出 True/False 导致解析失败）
