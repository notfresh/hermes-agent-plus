请探索当前项目 agent-loop里agent/conversation_loop.py#L588-L5776行的human in loop核心逻辑，也就是当权限需要人审核的逻辑，并且邀请人批准的核心逻辑，看看是否存在，如果存在，请写一个简单的demo，并且在主时中标明源逻辑位置所在源码文件和函数


沉淀一下本次对话的核心收获


参考这个关键函数速查表

| 行号 | 函数名 | 作用 |
|------|--------|------|
| 15384 | `main()` | CLI 入口，参数解析 |
| 15674 | `if query or image:` | 单次/交互模式分叉 |
| 15793 | `cli.agent.run_conversation()` | 进入 Agent 核心 |
| 12749 | `cli.run()` | 交互模式主循环 |
| 243 | `handle_enter()` | 交互模式下按回车后逻辑 |
| 588 | `run_conversation()` | Agent 核心引擎（真身） |
| 196 | `_strip_reasoning_tags()` | 清洗推理标签 |
| 2639 | `_cprint()` | 打印输出 |