---
name: axgraph
description: Use when querying or maintaining the AX-GRAPH Hermes source map.
---
# axgraph Skill
先读 [AX-GRAPH/AGENTS.md](../../../AX-GRAPH/AGENTS.md) 和 [SCHEMA.md](../../../AX-GRAPH/SCHEMA.md)，但不要进入该目录。
所有脚本使用项目根目录的 `.venv/bin/python` 执行。
从仓库根目录运行 `.venv/bin/python AX-GRAPH/graph_query.py ...`；图谱产出统一写入 `AX-GRAPH/`。
改图前先读源码，行号、`CALLS.at_line` 和 `DEPENDS_ON.weight` 必须实测。
添加节点前查重；增删节点后运行 `.venv/bin/python AX-GRAPH/graph_query.py --validate`，确保 Error 为 0。
不做全量自动重建，不引入 tree-sitter、MCP、SQLite；遇到架构归属或批量漂移先询问维护者。
