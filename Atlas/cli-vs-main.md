# cli.py 与 hermes_cli/main.py 的关系

## 一句话总结

`main.py` 是 CLI 框架入口（路由器+所有子命令的 handler），`cli.py` 是聊天子系统。`main.py` 做前置准备然后委托给 `cli.py`。

## 架构分层

```
hermes                    (命令行入口，由 setup.py entry_points 定义)
  │
  └─ hermes_cli/main.py::main()    — 解析 argv，构建 argparse 解析器
       │
       ├─ args.func == cmd_chat    — 默认 / 显式 chat
       │    ├─ cmd_chat() 做前置准备
       │    │  ├─ session 恢复
       │    │  ├─ xAI 退役检查
       │    │  ├─ 首次运行检测
       │    │  ├─ 同步技能
       │    │  ├─ safe/yolo mode
       │    │  └─ ... 其他框架级工作
       │    │
       │    ├─ 走 TUI → _launch_tui() 启动 Node 进程
       │    └─ 走 CLI → from cli import main as cli_main
       │                   └─ cli_main(**kwargs) → HermesCLI
       │
       ├─ args.func == cmd_setup   → 配置向导
       ├─ args.func == cmd_tools   → 工具集管理
       ├─ args.func == cmd_cron    → 定时任务
       ├─ args.func == cmd_model   → 模型切换
       └─ ... 其他 30+ 子命令
```

## 分派机制

`main.py` 第 13249-13250 行：

```python
chat_parser.set_defaults(func=cmd_chat)
```

所有子命令 parser 都绑定了自己的 `func`，然后在第 15180 行统一分派：

```python
if hasattr(args, "func"):
    args.func(args)
```

## cmd_chat() 转发到 cli.py 的位置

`hermes_cli/main.py` 第 2474-2500 行：

```python
from cli import main as cli_main

kwargs = { "model": ..., "provider": ..., "toolsets": ..., ... }
cli_main(**kwargs)
```

## 直接运行 `python cli.py`

`cli.py` 独立可执行，末尾用 `fire.Fire(main)` 暴露参数：

```bash
python cli.py                          # 启动交互模式
python cli.py --query "你好"           # 单次查询
python cli.py --toolsets web,terminal  # 指定工具集
python cli.py --list-tools             # 列出工具
```

跳过 `main.py` 的所有前置处理（profile 切换、setup 检测、技能同步等），是轻量快捷通道。

## 关键对比

| 维度 | `main.py` | `cli.py` |
|------|-----------|----------|
| 角色 | CLI 框架入口 + 子命令路由器 | 交互式聊天引擎 |
| 行数 | ~15186 行（含所有 cmd_xxx） | ~15903 行（纯聊天） |
| 管什么 | 所有 `hermes <subcommand>` | 仅聊天交互循环 |
| 前置处理 | profile、session、safe mode、技能同步等 | 无框架级处理 |
| 被谁调用 | `hermes_cli` entry_points → `main()` | `main.py::cmd_chat()` 或 `fire` |
| 核心类 | 无单一核心类 | `HermesCLI` |

## 典型调用链

```
hermes chat --model claude
  → hermes_cli/main.py::main()
    → build_top_level_parser(), chat_parser.set_defaults(func=cmd_chat)
    → args.func(args) → cmd_chat(args)
      → 前置处理（session 恢复、env 设置……）
      → from cli import main as cli_main
      → cli_main(**kwargs)
        → HermesCLI 实例化
        → 用户输入循环
        → AIAgent (run_agent.py)
        → 模型调用 + 工具执行
```
