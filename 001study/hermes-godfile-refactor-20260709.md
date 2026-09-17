# Hermes 2026 七月~九月 god-file 重构风暴 —— 记录与实证

> 记录一次把 Hermes 核心的巨型单文件（god-file）体系性地拆成细粒度模块的大规模重构，
> 以及一个小研究分支（`source-code-read`）恰好停在本轮重构中段时撞上的所有副作用。
> 数据取自 `notfresh/hermes-agent-plus` fork 的本地 git 历史。

---

## TL;DR

2026 年 7 月中到 9 月初，NousResearch/hermes-agent（及其同步 fork）内部执行了一轮**全库规模的"化巨为细"重构**：
把几千上万行的 god-file（核心 loop、CLI 编排器、tools 编排等）拆成大量细粒度模块，同时大规模压缩注释、机械批量地给旧调用点重新指路（repoint）。

- 提交号上：约 **55 天净增 15,000+ 个提交**，其中单日峰 **2026-09-02 一天约 4,000 个**
- 主力：维护者 **Teknium** 一人，多数是 `refactor` / `simplify(compat)` / `fix(ci-fallout)` 这类**机械批量**提交
- 关键文件实测：`run_agent.py` 约 11k~12k 行 → **~1.5k 行**；`cli.py` 约 11k 行 → **~4.7k 行**；`model_tools.py` → **~0.9k 行**
- 这不是普通 bugfix 堆积，而是维护者把大量时间花在"拆模块 + 压缩注释 + 在几十上百个文件间 repoint 调用点"上

**教训（对研究分支而言）**：在一个大仓库上长时间浅拉、且不拉全祖先，会让 `.git/shallow` 里错落出"假根"，
把本可 merge 的分支与上游拆成看似"无关"的关系；若再恰好停在一次大重构的中段，merge 时就会撞上一批由"上游大改写"造成的冲突。

---

## 1. 为什么会注意到这件事

在 `source-code-read` 上排查"分支没根 / 无法 merge main"时，需要理解"main 相对分支净增的 15,336 个提交到底
是些什么"。初步判断它像异常爆发（"才 40 天怎么可能这么多提交"），深入后确认：**不是 bug，是一个极其密集但真实的重构窗口。**

关键事实帮我们聚焦：

- 共享祖先（fork 分叉点）`3aeded6e32` 建在 **2026-07-20**
- `source-code-read` 此后只加了 ~14 个自己的提交（AX-GRAPH / 001study 等，到 09-06）
- 而 main 从 07-20 同步上游一直推进到 09-05，**净增 15,336 个提交**
- 这 15,336 的日期分布极不均匀：**2026-09-02 一天就有 3,990 个**

### 单日 4000 提交怎么来的

| 按 author 的年月归组(commit 时间戳都被打到同一批) | 数量 |
|---|---|
| 2026-09（本身） | ~4,800 |
| 2026-08 | 218 |
| 更早散落 | ~20 |

再看提交者：**2026-09-02 那 3,990 个里，4,389 个是 Teknium**（Nous Research 维护者）。
而那 4,389 个里 **3,326 个是 `refactor`**，其余大量是 `fix(ci-fallout)` / `simplify(compat)` / `test-seams` 等"重构后的扫尾"。
——也就是说：**一位维护者在连续时间里批量地把代码拆细、把旧的引用重新指路**，从而出现一天数千个"小而机械"的 commit。

一句话：40 天 15k 提交，不是 40 天均匀堆积，而是集中在 9 月初、以某一次 massive rebuild 形态出现的。

---

## 2. 修复"没有共同祖先"的插曲（假根）

最初 `merge source-code-read main` 报 **`fatal: refusing to merge unrelated histories`**。
排查发现这纯属浅仓库的假象：

- `.git/shallow` 名单里，`source-code-read` 根 `e49d33e6` 以及更深的 `f72e64cb3a`、`38a4f39d`、
  `124f68a84e`、`3aeded6e32` 被标成了"假根"（grafted），git 遍历到它们就停下。
- 但它们的**父对象其实都完整躺在本地对象库**(`.git/objects` 约 1.3 GB)——只是被 shallow 名单切断了"下一跳"。
- 手动沿父链穿浅边界上行，发现 `124f68a84e` 的父正是 **`3aeded6e32`**，而那恰是 `main` 的真实祖先。

把这几条假根从 shallow 摘除后：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| `merge-base source-code-read origin/main` | 空(exit 1) | **`3aeded6e32`** |
| `source-code-read` 谱系深度(rev-list) | 11 | 16,388 |
| merge | `unrelated histories` | 正常 |

> 假根的本质是"git 还没下载该提交的祖先"，不是它真的没有祖先。
> 我们这里是此前多次浅拉叠加 + 大仓库没拉全的产物。

---

## 3. 重构的形态：全库"化巨为细"

用当前(merge 后的 main 树)实测几个原始 god-file 的现状：

| 文件 | 出处 AGENTS.md 描述 | 重构前参考口径 | 当前(2026-09) |
|---|---|---|---|
| `run_agent.py` | "AIAgent class — 核心 loop(~12k LOC)" | ~12k | **~1.5k 行** |
| `cli.py` | "HermesCLI — 交互编排器(~11k LOC)" | ~11k | **~4.7k 行** |
| `model_tools.py` | tools 编排/discovery/builtin | 被反复拆分引用 | **~0.9k 行** |
| `hermes_cli/main.py` | 拆 cli 的逻辑出口 | — | merge 冲突一段就 `+2483/-14237` |

`run_agent.py` 从"几千上万行一个文件"瘦到 1.5k 左右，`model_tools.py` 到 0.9k，
`agent/` 目录下细模块多到 **~259 个文件**——这是把"窄腰"工程哲学落实到文件形态的直接结果。

### 提交主题词频（2026-09 起）

| 主题词 | 计数 | 含义 |
|---|---|---|
| `compact` | 817 | 压缩 docstring / 注释体量 |
| `refactor(hermes_cli):` | 607 | CLI 侧拆分 |
| `refactor(tools):` | 308 | tools 目录拆分 |
| `refactor(gateway):` | 258 | gateway 拆分 |
| `extract` | 239 | 抽出函数/模块 |
| `inline` | 188 | 内联单点调用 |
| `refactor(agent):` | 131 | agent 核心拆分 |
| `dedupe` | 110 | 去重 |
| `refactor(computer_use)` / `tui_gateway` / `state` | 88/71/88 | 各子域 |

这些词串起来就是 AGENTS.md 自己提倡的那条方法论：
**"refactor god-files into clean modules … huge +N/-N refactors merge regularly"**（把 god-file 拆成干净模块，大 diff 属常态）。

### 代表性提交样本

- `2f86ce2eb0  refactor(cli-main): split cmd_chat (first-run guard, --query-file, passthrough table), tighten ... / compact comments and docstrings (every WHY kept); repoint xai test to the flow's real module` （2026-09-02，Teknium）
- `53db597201  simplify(compat): hermes_state — drop 81 re-exports + 3 registry aliases + 3 shims, repoint 45 callers + 60 test files`（2026-09-03）
- `7b8c11bcf7  simplify(compat): models — drop 52 re-exports from hermes_cli.models, repoint 16 callers + 41 test files`（2026-09-03）

可见重构的**副产物形态**：凡是原来在 god-file 里 `re-export`(从别的模块抄名字再导出) 的地方，
现在都 **drop 掉 re-export、把每个旧 import 站点(repoint caller / test file)改指向"定义所在的新模块"**。

> 这是典型"窄腰"工程——核心只保留真正的定义，不再做历史上为了兼容而保留的转发层(compat facade)。

---

## 4. 重构对 merge 的直接影响：`hermes_cli/main.py` 那次冲突

正式 merge `origin/main` 进 `source-code-read` 时，只有 4 个文件冲突、每个 1 块：

| 文件 | 结论 | 依据 |
|---|---|---|
| `.gitignore` | 取 main | source 侧加的两行已被 main 收录 |
| `ui-tui/package.json` | 取 main | source 是旧依赖树；main 是 45 天后的锁定版本 |
| `package-lock.json` | 取 main | source 侧删 556 行，强保致依赖错乱 |
| `hermes_cli/main.py` | **取 main** | **main 侧被大改写：相对 source 是 +2483/-14237** |

第 4 项正是本轮重构的直接投影：source(停在 7-20) 侧的这个文件几乎没人碰（只在 npm 参数加过 1 行 `--include=optional`），
而 main 在这 45 天里把它按"拆 cli/logic 出口"的思路大改了上下一万行，导致 merge 无法行级对齐，
git 把整个函数块都丢给手工仲裁 → 现实里直接取 main 权威即可，source 那行已随 main 语义演进而过时。

### 为什么"停在中段"就特别易冲突

如果 fork 停在一次**稳定提交**,merge 通常干净；这里恰恰停在重构**进行中段**——
上游要拆的东西很多还没落定、facade/compat 还反复增删。于是
**差异面巨大 + 变量命名/文件归属都变了**，冲突自然多且"体积恐怖"。
但单看冲突文件数(4个、每个1块)，其实这场 merge 冲突面很小——真正大的是那份**改写的体积**，不是冲突数量。

---

## 5. 我们做了什么 / 学到什么

过程：
1. 建备份分支 `backup/source-code-read-<ts>`（merge 前自动留底）
2. 在孤立临时 worktree 里先 dry-run(`--no-commit`)摸清冲突，跑完即清
3. 正式普通 merge，4 个冲突逐一仲裁，以 main 版本为权威
4. 记录了 shared-zero 标签 `notfresh-zero`(指向 `3aeded6e32`)

方法论要点：
- **不要在一个大仓库上长期只做浅拉却不同步拉全祖先**——假根会错落累积，最后把分支与 main 拆成"看似无关"
- fork 停在重构中段时，merge 冲突以"上游改写体积"为主 → 优先确认本侧有没有非要保留的自有改动，
  没有就大胆取上游权威版本，避免背一份过时的旧依赖/旧结构
- 全库重构窗口期的高频提交绝大多数是**同质机械 commit**（refactor/simplify/repoint），
  统计时勿误当"每天几百个真 bugfix"



（本文所有数字均为实测，可复跑复核。）

*Article date: 2026-09-06 · scope: 001study · related tag: notfresh-zero*
