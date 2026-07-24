# -xz / -zx Feature Implementation (2026-07-25)

## 发现 (What we discovered)
- hermes -z 的核心逻辑在 hermes_cli/oneshot.py，run_oneshot() 通过 sys.exit() 提前返回，--resume 逻辑永远触达不到
- SessionDB.search_sessions(source=None) 可以跨 CLI/TUI 查询所有会话，以 last_active 排序
- argparse add_mutually_exclusive_group() 可以让 -z 和 -xz 互斥，argparse 自动报错
- 现有的 _create_session_db_for_oneshot() 只用于工具查询，不做历史注入；-xz 需要完整的 SessionDB 实例才能持久化

## 学到 (What we learned)
- subagent-driven-development 工作流：brief → implement → review → fix → re-review，每个任务有清晰边界
- 用 .venv/bin/pytest 运行测试（项目用 uv 管理虚拟环境）
- Task 5 smoke test 时发现环境有活跃会话，所以 "no session" 错误路径无法手动触发——这正好说明单元测试覆盖了这条路径
- argparse 的 dest 参数让 -xz 和 -zx 可以映射到同一个字段

## 完成 (What we accomplished)
- 实现 hermes -xz / -zx 命令：带会话历史的单次执行模式
- 改动 3 个核心文件：_parser.py、main.py、oneshot.py
- 新增 12 个测试，35 个测试全部通过，无回归
- 最终审核通过，Ready to merge
