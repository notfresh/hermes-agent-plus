# Hermes 源码阅读指南

快速找到核心，理解原理，不被噪音淹没。

---

## 核心骨架：只有 6 个文件

整个 Hermes 的核心逻辑集中在根目录的几个 `*.py` 里，其他都是辅助/平台/插件。

| 文件 | 大小 | 是什么 |
|------|:----:|--------|
| `agent/conversation_loop.py` | ~5,800 行 | **真正的核心循环** — 消息→LLM→工具的闭环 |
| `run_agent.py` | 306 KB | `AIAgent` 类 — 引擎装配与状态管理 |
| `agent/prompt_builder.py` | ~2,000 行 | System Prompt 组装 |
| `agent/tool_executor.py` | ~1,800 行 | 工具调用调度 |
| `model_tools.py` | 65 KB | 工具注册、发现、分派 |
| `hermes_state.py` | 351 KB | SQLite 会话持久化 |

## 建议的阅读顺序

```
1. Atlas/hermes-macro-architecture.md  ← 5 分钟，建立六层架构心智模型
2. Atlas/lesson1-agent-loop.md        ← 10 分钟，理解主循环三阶段
3. agent/conversation_loop.py :: run_conversation()  ← 真正的核心
4. run_agent.py :: AIAgent.__init__()  ← 理解引擎装配了什么
5. agent/prompt_builder.py            ← System Prompt 怎么拼的
6. model_tools.py                     ← 工具系统怎么工作的
```

## 实用阅读技巧

### 1. 跳到关键函数，别从头读到尾

每个核心文件都很大（`conversation_loop.py` 5,800 行，`run_agent.py` 6,600 行），不要从第 1 行开始读。

```bash
grep -n "def run_conversation" agent/conversation_loop.py
# 输出: 588 → 从这里开始读

grep -n "class AIAgent" run_agent.py
# 输出: 399

grep -n "def __init__" run_agent.py
# 输出: 409
```

用 `Read` 工具时指定 `line_offset` 直接从关键行开始。

### 2. 理解主循环的 3 步模式

`run_conversation()` 的核心 while 循环只有 3 步：

```
① 组装 messages → 调 LLM（API call）
② 解析响应 → 有 tool_call 就执行工具
③ 结果塞回 messages → 回到 ①
```

看懂这个循环，就看懂了 80% 的 Hermes。

### 3. 先用 `Atlas/` 文档建立心智模型

`Atlas/` 下的文档是现成的阅读地图：

- `hermes-macro-architecture.md` — 六层架构总览，理解文件之间的关系
- `lesson1-agent-loop.md` — 逐段分析主循环代码，带着理解去读源码
- `cli-vs-main.md` — 两个入口的区别

先读这些再碰源码，效率翻倍。

### 4. 分清核心与外围

**核心（优先读）：**

| 路径 | 为什么核心 |
|------|-----------|
| `agent/conversation_loop.py` | Agent 主循环——消息→LLM→工具的闭环 |
| `run_agent.py` | AIAgent 引擎定义 |
| `agent/prompt_builder.py` | System Prompt 组装，影响每次 LLM 调用 |
| `agent/tool_executor.py` | 工具执行分发 |
| `model_tools.py` | 工具注册、schema 收集、发现 |
| `toolsets.py` | 工具集定义——哪些工具在哪些场景可用 |
| `hermes_state.py` | 会话/状态持久化 |
| `utils.py` | 各种工具函数 |

**外围（需要时再看）：**

| 路径 | 是什么 | 读它的时机 |
|------|--------|-----------|
| `cli.py` | CLI 交互引擎 | 想理解用户输入如何流入 AIAgent 时 |
| `hermes_cli/` (140+ 文件) | 子命令、配置、安装 | 需要改某个 `hermes xxx` 命令时 |
| `gateway/` | 消息平台适配层 | 需要调试 Telegram/Discord 等平台时 |
| `plugins/` | 插件系统 | 需要理解插件机制或写插件时 |
| `tools/` | 具体工具实现 | 需要理解某个具体工具的行为时 |
| `cron/` | 定时任务调度 | 需要理解 cron 机制时 |
| `container/` | Docker/容器逻辑 | 容器部署相关 |
| `website/` | 文档站点 | 非运行时相关 |

### 5. 用 Grep 做术语反向索引

遇到不懂的术语，先搜它在源码里怎么用的：

```bash
# 搜索关键符号的定义和使用
grep -rn "def handle_function_call" model_tools.py
grep -rn "class HermesCLI" cli.py
grep -rn "_HERMES_CORE_TOOLS" toolsets.py
```

### 6. 关注导入链，理解依赖关系

核心依赖链：

```
tools/registry.py                    ← 无依赖，被所有工具文件导入
       ↓
tools/*.py                          ← 各自调用 registry.register()
       ↓
model_tools.py                      ← 触发工具发现 + 分派
       ↓
run_agent.py, cli.py, gateway/...   ← 消费方
```

agent 内部依赖链：

```
agent/prompt_builder.py             ← 拼 System Prompt
       ↓
agent/tool_executor.py              ← 执行工具调用
       ↓
agent/conversation_loop.py          ← 主循环，编排上面两者
       ↓
run_agent.py :: AIAgent             ← 对外暴露的引擎类
```

### 7. 用 `wc -l` 快速评估文件规模

```bash
# 看哪些文件最大，决定了阅读策略
wc -l cli.py run_agent.py agent/conversation_loop.py hermes_state.py
# 15903   306448    5780    351402
# 大文件需要跳着读，小文件可以通读
```

### 8. 忽略的噪音（不要在这上面花时间）

- `__pycache__/`、`.pytest_cache/`、`node_modules/` — 生成物
- `locales/` — 多语言翻译文件
- `assets/`、`infographic/` — 素材和图表
- `nix/`、`docker/`、`packaging/` — 打包部署
- 测试文件（`tests/`）— 理解原理时先不看
