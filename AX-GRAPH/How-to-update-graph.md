# How-to-update-graph.md — 按 commit 增量更新 AX-GRAPH

> 适用场景：hermes-agent-plus 提交了若干新 commit，想增量更新图（不全量重建）。
> 原则：**最小更新单元 = 单个 function 节点**；按 commit diff 反推受影响节点，逐个改。
>
> 维护者：Hermes（郑旭） · 任务编号 0012 · 与 AGENTS.md 配合使用

---

## 1. 核心思路

图里的"会动的字段"和"不会动的字段"必须分清：

| 字段类型 | 例子 | commit 后是否要改 |
|---|---|---|
| **锚点（必动）** | `path = "agent/skill_commands.py"`、`files+lines = "725"` 锚点 | 改文件路径/行号→**改** |
| **调用关系（常动）** | CALLS 边的 `at_line = 725` | commit 改了调用点→**改** |
| **依赖权重（偶动）** | DEPENDS_ON 的 `weight = 12` | 文件新增/删除 import→**改** |
| **语义描述（极少动）** | `desc = "加载 skill 载荷"`、`kind = "function"` | commit 改了函数语义→**改**（要读代码确认） |
| **feature 节点** | `feature.skill_load` 自身 | 仅当该功能被重构或废弃→**改**；纯 bugfix 不动 |

**所以 80% 的更新工作集中在三件事**：
1. 找新行号（grep 当次核对，AGENTS.md 铁律 1）
2. 找新调用点行号（同上）
3. 重新计数 import 次数（变化小，可选）

---

## 2. 标准流程（按 commit 增量）

### Step 1：列出 commit 改了哪些文件

```bash
# 单 commit
git show --stat <sha>

# 一段范围（如 source-code-read 分支领先 5 个 commit）
git log --oneline origin/source-code-read..HEAD
git diff --stat origin/source-code-read..HEAD
```

### Step 2：抽出 commit 改动的函数清单

```bash
# 关键：commit 实际改/加/删了哪些函数定义？
git diff origin/source-code-read..HEAD -- <file> | \
  grep -nE '^\+.*(def |class )' | sort -u
```

这一步给你**受影响的函数名清单**（理想态 = 单个 function，现实通常是 5-20 个一组）。

### Step 3：在图里查每个函数节点的当前位置

```bash
python3 graph_query.py <func_id_or_keyword>
```

对比"图的当前 path/lines"和 Step 2 的函数清单——列出**真正需要改**的节点。

> 例外：如果 commit 改了某个函数但**该函数未在图中**（L1/L2 没建节点），那不动图——但要在心里记下"这个函数现在值得入图了"。

### Step 4：grep 当次核对（AGENTS.md 铁律 1）

```bash
grep -nE '^\s*(async )?def |^\s*class ' <new_path>
```

确认每个受影响函数的**新行号**。

### Step 5：分类改图

| 变化类型 | 改什么 |
|---|---|
| 函数行号 ±几行 | `files+lines` 锚点 + 所有指向它的 CALLS 边的 `at_line` |
| 函数被改名 | 改 `id` + 全图搜老 id 替换 + 关联边改 `from/to` |
| 函数被删除 | 删除节点 + 全图搜 id 清边（`grep -r "<id>" Layer-*.toml`） |
| 函数被新增 | 走 AGENTS.md §6 增节点流程（决定挂哪个 L3 文件、feature 归属） |
| import 路径变 | DEPENDS_ON 边的 `weight` 重测 + 模块路径换 |
| 函数签名变（参数加 default 等） | 通常不改图——签名不在图里；除非语义真变了 |

### Step 6：单点验证 → 收工验证

```bash
# 单点
python3 graph_query.py --validate <func_id>

# 收工
python3 graph_query.py --validate
# 目标：0 Error（Warning 是历史欠账，可暂缓，AGENTS.md 铁律 5）
```

---

## 3. 典型场景速查

### 场景 A：单 commit 只改了一个函数实现（最理想）

```bash
# 1. 看 commit 范围
git show --stat <sha>
#  1 file: agent/skill_commands.py | 8 ++--
#  说明只动了 skill_commands.py（多个函数一起改）

# 2. 抽受影响的函数
git show <sha> -- agent/skill_commands.py | \
  grep -nE '^\+.*(async )?def ' | sort -u
#  +    def _load_skill_payload(self, ctx, ...):
#  +    def _load_skill_prompt(self, ...):
#  → 2 个函数需要检查

# 3. 在图里查每个
python3 graph_query.py _load_skill_payload
python3 graph_query.py _load_skill_prompt

# 4. 改 [files+lines] 锚点（如果行号变了）
# 5. 改所有 CALLS 边 at_line（grep 找新调用点）
# 6. 验证
```

### 场景 B：commit 改了一组函数（小重构）

同场景 A，只是 Step 2 抽出的清单更长（5-20 个）。**逐个**走 Step 3-6，不要批量盲改。

### 场景 C：commit 重命名/拆分/合并函数

- **重命名**：改 id + 全图替换（`grep -rl "<old_id>" AX-GRAPH/`）
- **拆分**：原节点降级/移除，新增子节点（走 AGENTS.md §6）
- **合并**：反向处理

### 场景 D：commit 改了 import 路径（模块迁移）

- DEPENDS_ON 边的 `weight` 重测（import 计数变了）
- 如果改了模块路径，所有引用该模块的 file.* 节点的 `path` 也要改
- 影响范围大时考虑跑全量 `--validate` 而不是单点

---

## 4. 反模式（不要这么做）

❌ **不要全量重建**。AGENTS.md §1 明确禁止 tree-sitter/MCP/SQLite 等"自动重建"工具——人是学习者，建图过程 = 读源码学习过程。

❌ **不要"看 commit message 改图"**。commit message 是给人看的 summary，跟实际 diff 可能差很远（refactor、chore 经常改很多但 message 一句话）。

❌ **不要批量改数字**。哪怕用工具（如未来的 `--suggest`）列出漂移，也必须**先读对应源码确认语义没变**再改。

❌ **不要顺手清 Warning**。`--validate` 跑出的历史 Warning 是人积累的欠账，清掉之前先确认是不是真的无效。

❌ **不要"为了更新而更新"**。如果一段时间没碰图、不查图，那段时间也不必更新图——图的价值 = 被查询频率，更新与查询节奏匹配。

---

## 5. 已实现的工具

### `--update <func_id>`（2026-09-04 用户拍板落地的第一版）

**默认 dry-run**：打印 git diff 风格的 diff，不写盘。

```bash
python3 graph_query.py --update func.graph_query.ppath
# 输出：
#   漂移: 行号 29 → 84
#   计划改动：
#     -path = "AX-GRAPH/graph_query.py:29"
#     +path = "AX-GRAPH/graph_query.py:84"
#   ⚠️ dry-run，未写盘。加 --apply 才真改。
```

**`--apply`**：真写盘 + 改前 validate + 改后 validate。

```bash
python3 graph_query.py --update func.graph_query.ppath --apply
# 改前 validate（已有错误则中止，避免乱改盘）
# 改盘
# 改后 validate（确保没引入新错）
```

**`--force`**：跳过改前 validate（用于修本身就报错的图——比如你看到的 "行号 29 不是 def/class" 错误就是要修的目标）。

```bash
python3 graph_query.py --update func.graph_query.ppath --apply --force
```

**YAGNI 边界（当前版本不支持）**：
- ❌ CALLS 边 `at_line` 同步刷新（用户首版只要 path 行号）
- ❌ 批量更新（当前只单点）
- ❌ 其他 kind 节点（只接 func.*，按 YAGNI 原则）
- ❌ 多 base 联动

**未来 `--suggest`**（仍是 TODO，未实现）：
- `--suggest <func_id>`：单点漂移报告（不直接改图）
- `--suggest` 无参：全图漂移清单（按漂移幅度排序）
- `--suggest --base-ref <git ref>`：相对某 commit 的漂移统计

> 关键约束（与 AGENTS.md §5 铁律一致）：工具只**建议/执行明确请求**，不主动改图；必须**先读代码再改图**——检测到漂移 ≠ 可以自动修。

---

## 6. 与其他文档的关系

- **AGENTS.md §1** — 为什么手动挡（学习导向 / 拒绝 tree-sitter）
- **AGENTS.md §5** — 协作铁律（行号当次 grep / 人在回路 / 关系实测 / 复用 id / 验证收工）
- **AGENTS.md §6** — 新增节点标准流程
- **AGENTS.md §7** — 什么情况必须问人
- **SCHEMA.md** — 编辑手册（节点/边字段细则）
- **TODO.md** — `--suggest` 工具的待办与设计意图
- **usage-skill-load.md** — 实战记录模板（更新图后顺手记一笔）

---

## 7. 自我提示

更新图最容易犯的错：**觉得"行号而已，改数字就行"**。
但每次改图都是一次读源码的机会——5 分钟的 grep 比 5 小时的重读值。
**速度不是目的，理解是。** 哪怕今天只更新 1 个节点，但理解了那个函数在做什么，就赚到了。