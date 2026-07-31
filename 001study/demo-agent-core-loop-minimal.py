"""
Agent 核心循环简化版 - 教学用

从 hermes-agent-plus 的核心循环代码提炼而来。
保留了最核心的 Message → LLM → Tool → Loop 模式。

简化说明：
- 去掉了错误处理、重试机制
- 去掉了上下文压缩
- 去掉了各种 provider 适配
- 去掉了 plugin 钩子
- 保留了核心架构
"""

from typing import Any, Dict, List, Optional

# ============================================================
# 模拟的组件（实际项目中这些是独立的复杂模块）
# ============================================================

class MockLLM:
    """模拟的 LLM 调用"""

    def __init__(self, model: str = "claude-3"):
        self.model = model

    def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        """
        返回模拟的 LLM 响应

        对应原始代码:
        - agent.conversation_loop.py:1436-1466 (LLM API 调用)
        - agent._interruptible_api_call()
        """
        # 简单模拟：检查最后一条消息
        last_msg = messages[-1] if messages else {}
        content = last_msg.get("content", "")

        # 如果用户说 "用 calculator 计算 1+1"，返回工具调用
        if "calculator" in content.lower() and "1+1" in content:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression": "1+1"}'
                        }
                    }
                ],
                "finish_reason": "tool_use"  # 对应 conversation_loop.py:1215
            }

        # 否则返回最终回复
        return {
            "role": "assistant",
            "content": f"我已经处理了你的请求: {content}",
            "finish_reason": "stop"
        }


class MockToolExecutor:
    """模拟的工具执行器"""

    TOOLS = {
        "calculator": lambda args: str(eval(args.get("expression", "0")))
    }

    def execute(self, tool_name: str, tool_args: Dict) -> str:
        """
        执行工具并返回结果

        对应原始代码:
        - run_agent.py:6165 (_execute_tool_calls)
        - agent/tool_executor.py (execute_tool_calls_sequential)
        - conversation_loop.py:4701-5055 (工具执行子流程)
        """
        if tool_name in self.TOOLS:
            result = self.TOOLS[tool_name](tool_args)
            return f"结果是: {result}"
        return f"未知工具: {tool_name}"


# ============================================================
# 核心循环 - 简化版
# ============================================================

def run_conversation_minimal(
    user_message: str,
    system_prompt: str = "你是一个有帮助的 AI 助手。",
    max_iterations: int = 10
) -> Dict[str, Any]:
    """
    Agent 核心循环的最小实现

    核心流程:
    1. 构建消息列表 (system + history + user)
    2. 调用 LLM 获取响应
    3. 检查 finish_reason:
       - tool_use: 执行工具 → 把结果加入消息 → 回到步骤 2
       - stop: 返回最终回复 → 结束

    对应原始代码:
    - conversation_loop.py:588 (run_conversation 函数定义)
    """

    # ===== 初始化消息列表 =====
    # 对应 conversation_loop.py:641-672
    # (build_turn_context 构建上下文)
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": user_message})

    # 初始化组件
    llm = MockLLM()
    tool_executor = MockToolExecutor()

    # 模拟可用的工具
    # 对应 agent.tool_executor.py 中的工具注册
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "计算数学表达式",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "数学表达式，如 1+1"
                        }
                    },
                    "required": ["expression"]
                }
            }
        }
    ]

    # ===== 核心循环 =====
    # 对应 conversation_loop.py:715 (while 循环条件)
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- 迭代 {iteration} ---")
        print(f"消息数量: {len(messages)}")

        # 步骤 1: 调用 LLM
        # 对应 conversation_loop.py:1185 (打印 API 调用日志)
        print("→ 调用 LLM...")

        # 对应 conversation_loop.py:1272-1320 (实际 API 调用)
        response = llm.chat(messages, tools)

        # 步骤 2: 将 assistant 消息加入历史
        # 对应 conversation_loop.py:2200-2400 (消息持久化)
        assistant_msg = {
            "role": response["role"],
            "content": response.get("content")
        }

        # 如果有 tool_calls，添加到消息中
        # 对应 conversation_loop.py:1047-1068 (处理 tool_calls)
        if response.get("tool_calls"):
            assistant_msg["tool_calls"] = response["tool_calls"]

        messages.append(assistant_msg)

        # 步骤 3: 检查 finish_reason
        # 对应 conversation_loop.py:1728-1775 (提取 finish_reason)
        finish_reason = response.get("finish_reason", "stop")

        if finish_reason == "tool_use":
            # ===== 工具调用分支 =====
            # 对应 conversation_loop.py:4701 (进入工具处理子流程)
            print(f"🔧 发现 {len(response['tool_calls'])} 个工具调用")

            for tool_call in response["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_args = eval(tool_call["function"]["arguments"])

                print(f"   执行工具: {tool_name}({tool_args})")

                # 执行工具
                # 对应 run_agent.py:6241 (_invoke_tool)
                tool_result = tool_executor.execute(tool_name, tool_args)

                # 将工具结果添加到消息
                # 对应 conversation_loop.py:5034 (持久化 assistant tool-call turn)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result
                })

                print(f"   → {tool_result}")

            # 继续循环，让 LLM 处理工具结果
            # 对应 conversation_loop.py:5710 (continue 回到循环)

        elif finish_reason == "stop":
            # ===== 结束分支 =====
            # 对应 conversation_loop.py:1875 (提取最终回复)
            final_response = response.get("content", "")
            print(f"✓ 完成! 响应: {final_response}")

            return {
                "final_response": final_response,
                "messages": messages,
                "iterations": iteration,
                "completed": True
            }

    # 达到最大迭代次数
    # 对应 conversation_loop.py:737 (预算耗尽退出)
    return {
        "final_response": "达到最大迭代次数",
        "messages": messages,
        "iterations": iteration,
        "completed": False
    }


# ============================================================
# 运行示例
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("Agent 核心循环演示")
    print("=" * 50)

    # 示例 1: 需要工具调用
    print("\n>>> 示例 1: 使用 calculator 工具")
    result = run_conversation_minimal("请用 calculator 计算 1+1")

    print("\n" + "=" * 50)

    # 示例 2: 不需要工具调用
    print("\n>>> 示例 2: 普通对话")
    result = run_conversation_minimal("你好，请介绍一下自己")
