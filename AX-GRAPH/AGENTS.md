# AX-GRAPH — Hermes Agent 源码图（任务 0012）

> 给所有进入本目录的 AI 协作代理的操作约定。**先读本文件，再动任何文件。**
> 人看状态看 `README.md`，编辑细节看 `SCHEMA.md`。

## 1. 这个目录是什么

- **Hermes Agent 源码的"分层代码图"**：用 TOML 存储源码分布、模块抱团关系、功能实现路径，可查询、可审计、可长期积累。
- 任务编号 0012，维护者 Hermes（郑旭）。图目录：`hermes-agent-plus/AX-GRAPH/`（2026-08-29 由 X-GRAPH 改名）。
- **定位决策（2026-08-28，不可推翻）：原型、手动挡**。构建图的过程 = 读源码学习的过程。**拒绝引入 tree-sitter / MCP / SQLite 等自动化工具体系**（同类项目 colbymchenry/codegraph 已调研，明确不采纳）。你是学习者不是生产者——任何"我帮你全自动建图"的冲动都是错的。
- 当前状态：三层建成，4 个图文件，合并 119 节点 / 239 边 / 0 悬空（2026-08-29）。

## 2. 目录文件清单

| 文件 | 作用 |
|---|---|
| `Layer-1-Graph.toml` | 源码级分布：模块（12）+ 顶层散落文件 + hermes_cli 展开第一批 |
| `Layer-2-Graph.toml` | 簇级：agent 模块 4 个隐式簇 + 平铺未归簇文件 |
| `Layer-3-Graph-skill_load.toml` | 功能级：运行时 skill 加载链（/skills 命令、载荷加载） |
| `Layer-3-Graph-skill_startup.toml` | 功能级：hermes 入口 → 技能索引注入 system prompt（启动链） |
| `graph_query.py` | 查询 + 校验工具（自动合并所有 Layer-*.toml） |
| `SCHEMA.md` | **编辑手册**：节点/边必填字段、命名规则、示例。新增节点前必读 |
| `NodeDetails.toml` | 节点详细介绍（KV：节点id → 多行读码笔记），由 `-b` 维护 |
| `call_candidates.py` | CALLS 候选提取脚本（AST 提取调用+调用点行号，人工确认后入图） |
| `usage-skill-load.md` | skill-load 功能链的实战记录（模板参考） |

## 3. 三层结构：每一层回答什么问题

| 层 | 文件 | 粒度 | 回答的问题 | kind | 关系 |
|---|---|---|---|---|---|
| Layer-1 | `Layer-1-Graph.toml` | 模块/文件 | 代码分布在哪 | module / file | CONTAINS（归属）、DEPENDS_ON（耦合，weight=import 次数实测） |
| Layer-2 | `Layer-2-Graph.toml` | 隐式簇 | 谁跟谁抱团 | cluster / subpackage | CONTAINS（簇→成员）、DEPENDS_ON（簇间实测） |
| Layer-3 | `Layer-3-Graph-*.toml` | 功能/函数 | 功能怎么实现 | feature / function | REALIZED_BY（功能→实现函数）、CALLS（函数→函数，at_line=调用点行号） |

要点：
- **功能是横切多模块的**（skill-startup 横切 hermes_cli/ + cli.py + run_agent.py + agent/），cluster 表达不了，必须第三层。
- **隐式簇靠命名模式 + 依赖网维系，不靠目录**（agent/ 156 文件平铺只有 4 个小包）。
- **边可跨文件引用**（skill_startup 引用 skill_load 图的 `iter_skill_index_files`、引用 L1/L2 的 file.* 节点）——查悬空必须全量合并。

## 4. 查询速查（graph_query.py）

```bash
python3 graph_query.py <id或关键词>            # 查节点：详情 + 出边 + 入边
python3 graph_query.py <id> -c                 # 调用链展开（树形 + 调用点行号，可跳转）
python3 graph_query.py <id> -r                 # 反向调用链（谁在调用我）
python3 graph_query.py <id> -e                 # 关系人话解读
python3 graph_query.py <id> -d                 # 末尾显示该节点详细介绍（NodeDetails.toml）
python3 graph_query.py -b <id>                 # 构建/编辑详细介绍：打开 $EDITOR(vim) 编辑临时文件，保存退出自动写入
python3 graph_query.py -b <id> --text "..."    # 直写详细介绍（AI/脚本友好）；空文本=删除该详情
python3 graph_query.py <关键词> -s             # List 模式（只列匹配不展开）
python3 graph_query.py --validate              # 全量校验
python3 graph_query.py --validate -l 3         # 只校验第 3 层文件
python3 graph_query.py --validate <节点id>     # 只校验该节点及其关联边
python3 graph_query.py <id> -l core            # 只看 core 架构层
```

- 输出 `path= ./文件:行号` 可直接 Ctrl+点击跳转（VSCode）。
- 校验分级：**✗ Error（exit≠0，必须修）**=悬空边 / path 不存在 / 行号非 def/class / function 缺 path / kind 非法；**⚠ Warning（可暂缓）**=缺 layer / 缺 weight 等历史欠账。

## 5. 协作铁律（违反会被打回）

1. **行号当次 grep 实测，不凭记忆**。源码更新行号会漂移（`skill_commands.py` 的 `_load_skill_payload` 曾 725→138）。函数行号用 `grep -nE '^\s*(async )?def |^\s*class '` 当次核对。
2. **关系实测不编造**。DEPENDS_ON 的 weight=import 计数；CALLS 的 at_line=调用点行号；测不了就标 `note = "待验证"`，不许硬写。
3. **复用已有节点 id，不重复定义**。重复定义 = 后加载的覆盖先加载的。先 `python3 graph_query.py <名称>` 查一下节点存不存在。
4. **增删节点后必须跑 `--validate`，0 Error 才能收工**。全量跑有历史欠账 Warning 是正常的，不许顺手"清理"旧数据（那是人决定的事）。

## 6. 新增节点的标准流程

1. 读目标源码，定位函数/类定义行号（grep 实测）。
2. 读 `SCHEMA.md` 确认必填字段与 id 命名规则。
3. 决定挂哪个文件：新功能链 → 新建 `Layer-3-Graph-<feature>.toml`；已有功能链 → 追加对应文件；跨层缺 file 节点 → 补 L1/L2（问人）。
4. 按格式加 `[[nodes]]`（id/kind/path/layer/desc）+ 关联边（CONTAINS 归属、CALLS 调用、REALIZED_BY 挂 feature）。
5. `python3 graph_query.py --validate <新节点id>` → 0 错误。
6. 用查询命令验证输出正常（`-c` 展开、`path=` 可跳转）。

## 7. 什么情况必须问人（郑旭），不要自作主张

- **新功能链立项**（要不要建 Layer-3 新文件、feature 命名）。
- **行号大规模漂移**（源码大改后，全图行号审计）。
- **删除被跨图引用的节点**（如 `func.agent.skill_utils.iter_skill_index_files` 被两个 L3 图引用）——删前 `grep -r "<id>" Layer-*.toml` 全图搜。
- **kind / layer 归属的判断**（module vs file、core vs entry 等拿不准时）。
- **查询工具的改动**（graph_query.py 属于工具层，改前确认）。

## 8. 背景知识（为什么这么设计）

- Hermes 的入口真相：`pyproject.toml:308` console_scripts 指向 `hermes_cli.main:main`，不是 cli.py；cli.py 是 cmd_chat 转调的第二层。
- 启动路径的"加载 skill" = **索引注入**（技能名+描述进 system prompt），不是读 SKILL.md 全文；全文是运行时 `skill_view` 才读。
- hermes_cli 是核心底座不是 CLI 壳（被依赖 970 次全库第一）——名字名不副实，图以实测为准。
