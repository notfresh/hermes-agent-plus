# RELEASE — AX-GRAPH 改进记录

> 项目内部的 release notes（不是真的发布版本——只是会话级改进留痕）。
> 维护者：Hermes（郑旭） · 任务编号 0012 · 按"一次改进一段"组织

---

## 2026-09-04 — diagnose / update / How-to 三件套

**主题**：从"图查询工具"走向"图分析与维护工具"——补齐诊断 + 自动化的两个长期缺口。

### 新增能力

#### 1. 功能链诊断 `--diagnose <feature_id>`

判断一条功能链是否符合"高内聚低耦合"，输出**客观指标 + 证据 + 建议**。

- 第一版只支持 `feature.*` 节点（按 YAGNI 原则）
- 第一版只实现**内部依赖密度**一个维度（入口数/密度/深度/散落 module/跨图调用）
- 默认人话输出；加 `--json` 输出结构化 JSON（AI/脚本友好）
- 与 `--purity` 平行：purity 看单函数 AST，diagnose 看链路网络拓扑

真实样例：
- `feature.skill-startup` → 🟢 low（1 入口 / 14 函数 / 散落 2 module）
- `feature.skill-load` → 🟡 medium（**4 入口 / 6 孤立 / 散落 agent+tools**——值得追问"职责是否模糊"）

#### 2. 按节点更新图 `--update <func_id>`

按 AGENTS.md §5 铁律 2（人在回路）落地的第一个"破坏性操作"命令。

- **默认 dry-run**：打印 git diff 风格 diff，不写盘
- **`--apply`**：真改盘 + 改前 validate + 改后 validate（双重保险）
- **`--force`**：跳过改前 validate（修本就报错的图用——比如"行号 29 不是 def/class" 错误就是要修的目标）
- YAGNI 边界：只接 `func.*` 节点、单点、不刷 CALLS at_line

#### 3. 方法论文档 `How-to-update-graph.md`

把"按 commit 增量更新图"的思路 + 6 步流程 + 4 典型场景 + 反模式系统化。

- 核心论点：**最小更新单元 = 单个 function 节点**（commit 经常改一组，但锚点/调用点/权重的分类很清楚）
- 与 `AGENTS.md` / `SCHEMA.md` / `TODO.md` 的引用关系明确
- §5 同步从"待实现"改成"已实现"

### 修复

- `func.graph_query.ppath` 行号 29 → 84（graph_query.py 自己的工具函数，路径基线漂移）

### 文件清单

新建：
- `AX-GRAPH/diagnose.py` — 功能链诊断模块（与 `purity.py` 平行）
- `AX-GRAPH/update_graph.py` — 按节点更新图模块（与 `purity.py` 平行）
- `AX-GRAPH/How-to-update-graph.md` — 按 commit 增量更新的方法论

修改：
- `AX-GRAPH/graph_query.py` — 加 `--diagnose` / `--update` / `--apply` / `--force` / `--json` + 转发块
- `AX-GRAPH/AGENTS.md` — 查询速查加 2 行
- `AX-GRAPH/How-to-update-graph.md` — §5 从 TODO 改已实现（已在上面新建）
- `AX-GRAPH/base-file-graph_query/Layer-1-Graph.toml` — 1 行修复（ppath 行号 29→84）

### 思考留痕（供后续审视）

- **purity 重新评估**：今天你主动跑 `--purity func.graph_query.ppath` 才发现漂移——证明 purity 是"在用"的（之前我评估"没人用"是错的，被会话证明）。但 diagnose 还没经过实战，要等下次实际用上才知道。
- **`--update` 的 `--force` 设计**：发现铁律的边界——"改前 validate 失败就中止"在修复报错图时会卡死，所以加了显式 `--force`。这是铁律 2（人在回路）的延伸，而不是违背。
- **YAGNI 边界**：本会话所有新工具都明确写了"什么不接"——其他 kind 节点不接、批量更新不做、CALLS at_line 不刷。后续扩展要按需来，不要预先做。

---

## 模板（后续改进直接复制改）

```markdown
## YYYY-MM-DD — <一句话主题>

**主题**：<这段改进解决什么问题>

### 新增能力
#### 1. <能力名>
- ...

#### 2. <能力名>
- ...

### 修复
- ...

### 文件清单
新建：
- ...
修改：
- ...

### 思考留痕（供后续审视）
- ...
```