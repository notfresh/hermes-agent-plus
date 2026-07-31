# Report 1: 整体架构概览

## 项目基本信息

- **项目**: Hermes Agent (Nous Research)
- **本地路径**: `/root/projects/hermes-agent-plus`
- **Upstream**: NousResearch/hermes-agent (GitHub)
- **本地当前 HEAD**: `3aeded6e3` (最新的 fix/perf/test commit)
- **Python 文件总数**: 3129 个

## 巨量文件统计

| 文件 | 行数 | 说明 |
|------|------|------|
| `cli.py` | 15,903 | 交互式 CLI 编排器 + 所有 slash 命令处理 |
| `gateway/run.py` | 22,984 | 消息网关核心，多平台消息路由与 agent 生命周期管理 |
| `run_agent.py` | 6,629 | AIAgent 核心类（已部分提取到 agent/ 目录） |
| `hermes_state.py` | 7,781 | SQLite 会话存储 (FTS5) |
| `model_tools.py` | 1,381 | 工具编排与分发 |
| `batch_runner.py` | 1,321 | 批量轨迹生成 |
| `trajectory_compressor.py` | 1,574 | 轨迹压缩 |

## 目录结构

```
hermes-agent-plus/
├── cli.py                  # CLI 主入口 (~16K 行)
├── run_agent.py            # AIAgent 核心循环 (~6.6K 行)
├── model_tools.py          # 工具注册/调用/分发
├── toolsets.py             # Toolset 定义 (按平台分组)
├── hermes_state.py         # SQLite 会话数据库
├── hermes_constants.py     # 配置路径 (profile-aware)
├── hermes_logging.py       # 日志系统
├── batch_runner.py         # 批量处理
├── trajectory_compressor.py # 轨迹压缩 (训练数据)
├── agent/                  # 156 个文件 — agent 内部模块
├── tools/                  # 103 个文件 — 工具实现
│   └── environments/       # 终端后端 (local/docker/ssh/modal/daytona/singularity)
├── gateway/                # 消息网关 (~26K 行合计)
│   └── platforms/          # 20+ 平台适配器 (Telegram/Discord/Slack 等)
├── plugins/                # 插件系统
├── skills/                 # 内置 skills (按分类存放)
├── optional-skills/        # 可选 skills (不默认激活)
├── cron/                   # 定时任务调度
├── hermes_cli/             # CLI 子命令、setup 向导、皮肤引擎
├── ui-tui/                 # Ink (React) 终端 UI
├── tui_gateway/            # TUI 后端 JSON-RPC
├── acp_adapter/            # ACP 服务器 (编辑器集成)
├── tests/                  # pytest 测试 (~17K 测试)
├── web/                    # Web 仪表盘
└── apps/desktop/           # Electron 桌面应用
```

## 核心架构亮点

### 1. 设计哲学: "Core as a Narrow Waist"

- **Prompt 缓存不可破坏**: 任何改变过去上下文、切换 toolsets、重建 system prompt 的行为都会使缓存失效，导致成本倍增
- **能力尽量放到边缘**: 新功能优先走 CLI 命令+skill → 插件 → MCP 服务器，最后才考虑加核心工具
- **"Footprint Ladder"**: 扩展现有代码 > CLI+Skill > 服务门控工具 > 插件 > MCP > 核心工具（最后选择）

### 2. 文件依赖链

```
tools/registry.py  (无依赖，被所有工具文件导入)
       ↑
tools/*.py  (导入 registry 并在模块级调用 registry.register())
       ↑
model_tools.py  (导入 registry + 触发工具发现)
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

### 3. AIAgent 核心循环

```python
while (api_call_count < self.max_iterations and iteration_budget.remaining > 0):
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tool_call in response.tool_calls:
            result = handle_function_call(...)
            messages.append(tool_result_message(result))
    else:
        return response.content
```

### 4. 多表面架构

同一个 agent 核心运行在多个界面上:
- **CLI** (prompt_toolkit + Rich) — 默认界面
- **TUI** (Ink/React) — `hermes --tui`
- **消息网关** — Telegram/Discord/Slack 等 20+ 平台
- **Electron 桌面** — 独立 React 应用
- **Web 仪表盘** — 嵌入 TUI (通过 PTY WebSocket)

### 5. 插件系统

两种类型:
- **General Plugin** — lifecycle hooks + tools + CLI subcommands
- **Memory-provider Plugin** — 独立的 ABC 接口 (honcho/mem0/supermemory 等)
- **Model-provider Plugin** — 推理后端 (openrouter/anthropic/gmi 等)

### 6. 技能 (Skills)

- 自带 skills + 可选 skills (通过 `hermes skills install official/<cat>/<name>`)
- Curator 后台维护 — 自动归档陈旧的 agent 创建技能
- Skill 命令注入为 user message（而非 system prompt），保护缓存

## 疑问点

1. `gateway/run.py` 23K 行——为什么这样巨型？计划怎么拆？
2. agent/ 目录下有 156 个文件但 agent/__init__.py 几乎空的，只导入了 jiter_preload，其他模块怎么被发现的？
3. CLI 的 `hermes` 命令树是如何与插件动态注册的 argparse 结合的？
4. cron 调度器的 `no_agent` 模式如何工作？
5. 本地 fork (notfresh/hermes-agent-plus) 和 upstream 的差异有多大？

## 下一步

- **Phase 2**: deep_dive_agent — 深入 agent/ 目录，理解 agent 核心初始化、对话循环和工具执行流程
