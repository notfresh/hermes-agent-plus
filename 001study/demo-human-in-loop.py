#!/usr/bin/env python3
"""
Human in the Loop Demo - 简化版

展示 Hermes Agent 中的人机确认机制。
源逻辑位置：tools/approval.py::prompt_dangerous_approval()

核心流程：
1. 检测危险命令
2. 提示用户确认
3. 用户选择: once / session / always / deny
4. 执行或阻断
"""

import re
import time

# ============================================================
# 模拟 Hermes 的危险命令检测（源逻辑：tools/approval.py::DANGEROUS_PATTERNS）
# ============================================================

DANGEROUS_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*/', "delete in root path"),
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\brm\s+--recursive\b', "recursive delete (long flag)"),
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666)', "world-writable permissions"),
    (r'\bsudo\s+rm', "sudo delete"),
    (r'\bkill\s+-9\s+-1\b', "kill all processes"),
    (r'\bdd\s+.*if=', "disk copy"),
    (r'>\s*/dev/sd', "write to block device"),
]


def detect_dangerous_command(command: str) -> tuple[bool, str]:
    """
    检测命令是否危险。
    源逻辑：tools/approval.py::detect_dangerous_command()

    Returns:
        (is_dangerous, description)
    """
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, description
    return False, ""


# ============================================================
# 模拟用户确认（源逻辑：tools/approval.py::prompt_dangerous_approval()）
# ============================================================

def prompt_dangerous_approval(command: str, description: str, timeout_seconds: int = 30) -> str:
    """
    提示用户确认危险命令。
    源逻辑：tools/approval.py::prompt_dangerous_approval()

    返回值：
    - 'once':  仅本次允许
    - 'session': 当前会话期间允许
    - 'always': 永久允许
    - 'deny': 拒绝
    """
    print("\n" + "=" * 60)
    print("⚠️  检测到危险命令！")
    print("=" * 60)
    print(f"\n命令: {command}")
    print(f"原因: {description}")
    print("\n选择:")
    print("  [o] once    - 仅本次允许")
    print("  [s] session - 本次会话期间允许")
    print("  [a] always  - 永久允许")
    print("  [d] deny    - 拒绝执行")
    print()

    choice_map = {
        'o': 'once',
        'once': 'once',
        's': 'session',
        'session': 'session',
        'a': 'always',
        'always': 'always',
        'd': 'deny',
        'deny': 'deny',
    }

    # 模拟带超时的用户输入
    print(f"请输入选择 (默认 30 秒超时): ", end="", flush=True)

    # 简化版：直接用 input
    try:
        user_input = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        user_input = 'd'

    decision = choice_map.get(user_input, 'deny')

    messages = {
        'once': "✓ 允许本次执行",
        'session': "✓ 允许本次会话",
        'always': "✓ 永久允许",
        'deny': "✗ 已拒绝",
    }

    print(f"\n{messages[decision]}")
    return decision


# ============================================================
# 模拟工具执行（源逻辑：agent/tool_executor.py）
# ============================================================

def execute_command(command: str, approved: bool) -> str:
    """模拟命令执行"""
    if not approved:
        return f"❌ BLOCKED: {command}"

    # 模拟执行
    return f"✓ 执行: {command}"


# ============================================================
# 核心循环（模拟 Hermes 核心逻辑）
# ============================================================

def run_with_human_in_loop(command: str) -> str:
    """
    带人机确认的核心循环。

    对应源逻辑位置：
    - 检测：tools/approval.py::detect_dangerous_command()
    - 确认：tools/approval.py::prompt_dangerous_approval()
    - 执行：agent/tool_executor.py::_execute_tool_call()
    """
    # 步骤 1: 检测危险命令
    is_dangerous, description = detect_dangerous_command(command)

    if not is_dangerous:
        # 安全命令，直接执行
        return execute_command(command, approved=True)

    # 步骤 2: 提示用户确认
    decision = prompt_dangerous_approval(command, description)

    # 步骤 3: 根据用户决策执行或阻断
    if decision == 'deny':
        return execute_command(command, approved=False)

    # 步骤 4: 执行命令
    return execute_command(command, approved=True)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Human in the Loop Demo")
    print("=" * 60)

    # 测试用例
    test_commands = [
        "ls -la",                    # 安全命令
        "rm -rf /tmp/test",         # 危险命令
        "chmod 777 somefile",       # 危险命令
        "echo 'hello world'",        # 安全命令
    ]

    for cmd in test_commands:
        print(f"\n>>> 测试命令: {cmd}")
        result = run_with_human_in_loop(cmd)
        print(f"结果: {result}")
        time.sleep(0.5)
