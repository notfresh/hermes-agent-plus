#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_worker.py — 模拟 Hermes Kanban 的 worker 进程
===================================================

真实 worker 是一个完整 hermes 进程, dispatcher 拉起它时通过环境变量传任务:

    HERMES_KANBAN_TASK     = 任务 id  (真实里还带 HERMES_KANBAN_BOARD)
    HERMES_KANBAN_WORKSPACE = 工作目录

worker 内部调 kanban_* 工具 (kanban_show / kanban_heartbeat / kanban_complete /
kanban_block), 绝不 shell 出去调 CLI —— 这里对应的是 kanban_tools.py 那些工具
的"模拟实现": 直接 import kanban_mini 读写同一个 SQLite 库。

用法 (由 dispatcher spawn, 一般不要手动跑):
    HERMES_KANBAN_TASK=t_xxx python3 demo_worker.py [--mode normal|block|crash|forget]

模式:
    normal  干活 -> 心跳 -> complete (默认)
    block   干活到一半 block_task(kind=needs_input), 等人 unblock
    crash   干活到一半被信号杀死 (模拟 worker 崩溃)
    forget  正常退出但忘了调 complete (模拟协议违规)
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kanban_mini as kb

DB_PATH = os.environ.get("KANBAN_DEMO_DB", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "demo_kanban.db"))
WORK_SECONDS = float(os.environ.get("KANBAN_DEMO_WORK_SECONDS", "1.0"))


def log(msg: str):
    print(f"  [worker {os.getpid()}] {msg}", flush=True)


def main():
    task_id = os.environ.get("HERMES_KANBAN_TASK")
    ws = os.environ.get("HERMES_KANBAN_WORKSPACE", ".")
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    if not task_id:
        print("error: HERMES_KANBAN_TASK not set (spawned by dispatcher?)")
        sys.exit(2)

    conn = kb.open_db(DB_PATH)
    task = kb.get_task(conn, task_id)

    # ---- 相当于 kanban_show(): 读任务全文 ----
    log(f"领取任务 {task_id}: {task['title']!r} (assignee={task['assignee']}, "
        f"workspace={ws})")

    # ---- 模拟干活: 分两段, 中间心跳一次 ----
    time.sleep(WORK_SECONDS / 2)
    kb.heartbeat(conn, task_id)  # 相当于 kanban_heartbeat(note="...")
    log("进度 50%, 心跳一次")
    time.sleep(WORK_SECONDS / 2)

    if mode == "crash":
        # 模拟崩溃: 干活到一半被杀死, 没来得及 complete
        log("!! 突然崩溃 (模拟进程被杀), 没交卷")
        os.kill(os.getpid(), 9)
    elif mode == "forget":
        # 协议违规: 干净退出, 但忘了调 complete
        log("!! 忘了调 complete 就退出了 (协议违规)")
        sys.exit(0)
    elif mode == "block":
        log("遇到问题: 需要人来确认方案 -> block(needs_input)")
        kb.block_task(conn, task_id, reason="方案A还是方案B? 需要你拍板",
                      kind="needs_input")
        sys.exit(0)
    else:  # normal
        log("干完了 -> complete")
        kb.complete_task(conn, task_id, result="已输出500字摘要, 来源: 3篇论文")
        sys.exit(0)


if __name__ == "__main__":
    main()
