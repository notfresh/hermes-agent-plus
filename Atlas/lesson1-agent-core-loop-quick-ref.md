# Agent 核心循环快速参考

> 核心文件位置和关键代码行号速查

---

## 核心文件

| 文件 | 行数 | 作用 |
|------|------|------|
| `agent/conversation_loop.py` | 5,780 | 主循环逻辑 |
| `agent/tool_executor.py` | - | 工具执行（顺序/并行） |
| `run_agent.py` | - | `AIAgent` 类定义 |

---

## 关键代码位置

### 主循环入口
- **函数定义**: `conversation_loop.py:588`
- **循环条件**: `conversation_loop.py:715`
  ```python
  while (api_call_count < agent.max_iterations 
         and agent.iteration_budget.remaining > 0) \
         or agent._budget_grace_call:
  ```

### 每次迭代步骤

| 步骤 | 行号 | 说明 |
|------|------|------|
| 中断检查 | 720 | `if agent._interrupt_requested:` |
| 预算消耗 | 736 | `agent.iteration_budget.consume()` |
| 构建请求 | 864-930 | `api_messages` 准备 |
| LLM 调用 | 1436-1466 | `agent._interruptible_api_call()` |
| 工具执行 | 4701-5055 | `finish_reason == 'tool_use'` |

### 工具执行
- **入口**: `run_agent.py:6165` → `_execute_tool_calls()`
- **顺序执行**: `tool_executor.py` → `execute_tool_calls_sequential`
- **并行执行**: `tool_executor.py` → `execute_tool_calls_concurrent`

### 退出条件
| 条件 | 处理 |
|------|------|
| `finish_reason == 'stop'` | 提取文本回复，`break` |
| `finish_reason == 'tool_use'` | 执行工具，`continue` |
| `api_call_count >= max_iterations` | 退出循环 |
| `agent._interrupt_requested` | 用户中断 |

---

## 核心函数调用链

```
AIAgent.run_conversation()
  └→ run_conversation()              # conversation_loop.py:588
       ├→ build_turn_context()       # turn_context.py - 初始化
       ├→ [主循环]
       │    ├→ agent._interruptible_api_call()  # API 调用
       │    ├→ _execute_tool_calls()            # 工具执行
       │    └→ agent._compress_context()        # 压缩（如需要）
       └→ turn_finalizer.finalize()  # 收尾
```

---

## 调试技巧

- 在 `conversation_loop.py:1185` 添加日志查看每次 API 调用
- 在 `tool_executor.py` 添加日志查看工具执行
- 检查 `agent._api_call_count` 获取当前迭代次数
