#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_run.py — Hermes Kanban 原理演示剧本
=========================================

把 kanban_mini.py 的核心机制串成 6 个小场景跑给你看:

  A1  CAS 原子认领     两个 dispatcher 同时抢一个任务, 只有一人成功
  A2  单任务完整生命周期  create -> claim -> spawn -> complete, 全程事件审计
  B   父依赖接力        父任务 done 后, 子任务才从 todo 升 ready 被派工
  C1  崩溃恢复          worker 被杀, dispatcher 下个 tick 回收重派
  C2  协议违规熔断      worker 三次"忘了交卷", dispatcher 熔断不再重派
  D   人在环            worker block 等人, 人评论 + unblock, 任务复活

跑法:  python3 demo_run.py
需要:  Python 3.8+, 无第三方依赖 (标准库 sqlite3 / subprocess / threading)

对照真实实现:
  kanban_mini.py   <-  hermes_cli/kanban_db.py   (~9200 行)
  demo_worker.py   <-  tools/kanban_tools.py + agent 里的 KANBAN_GUIDANCE
  场景里的 tick    <-  gateway 里每 60s 一次的 dispatch_once
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kanban_mini as kb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "demo_kanban.db")
WORKSPACES = os.path.join(HERE, "workspaces")
WORKER = os.path.join(HERE, "demo_worker.py")
WORK_SECONDS = float(os.environ.get("KANBAN_DEMO_WORK_SECONDS", "1.0"))


# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------

def banner(text):
    print(f"\n{'=' * 70}\n■ {text}\n{'=' * 70}")


def status_line(conn, tid):
    t = kb.get_task(conn, tid)
    print(f"    {tid}  [{t['status']:<8s}] {t['title']}  -> {t['assignee']}")


def show_task(conn, tid):
    """看板 show 的简化版: 任务 + 评论 + 完整事件流 (审计轨迹)。"""
    t = kb.get_task(conn, tid)
    print(f"\n  ┌─ task {tid}  「{t['title']}」  status={t['status']}")
    for c in kb.list_comments(conn, tid):
        print(f"  │  comment [{c['author']}]: {c['body']}")
    rows = conn.execute(
        "SELECT kind, payload, created_at FROM task_events "
        "WHERE task_id = ? ORDER BY id", (tid,)).fetchall()
    for e in rows:
        print(f"  │  event  {e['kind']:<22s} {e['payload']}")
    print(f"  └─ (events: {len(rows)} 条, 全部持久化在 SQLite 里)")


def tick(conn, mode="normal", max_spawn=4):
    """跑一个 dispatcher tick, worker 以指定模式行为。"""
    spawn = (lambda t: kb.spawn_worker(t, WORKER, WORKSPACES,
                                       extra_args=[] if mode == "normal" else [mode]))
    return kb.dispatch_once(conn, spawn_fn=spawn, max_spawn=max_spawn)


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------

def scene_a1_cas(conn):
    banner("A1  CAS 原子认领: 两个 dispatcher 同时抢同一个任务")
    tid = kb.create_task(conn, "抢手任务: 谁抢到谁干", assignee="researcher")
    status_line(conn, tid)
    print("  开两个线程, 同时发起 claim_task() ...")
    results = {}
    barrier = threading.Barrier(2)

    def grab(name):
        c = kb.open_db(DB)          # 每个"dispatcher"自己的连接
        barrier.wait()              # 对齐起跑线, 制造真并发
        task = kb.claim_task(c, tid, claimer=name)
        results[name] = task is not None
        if task is not None:
            print(f"    ✓ {name} 抢到了  claim_lock={task['claim_lock']}")
        else:
            print(f"    ✗ {name} 空手而归 (WHERE status='ready' 没命中)")
        c.close()

    t1 = threading.Thread(target=grab, args=("dispatcher-A",))
    t2 = threading.Thread(target=grab, args=("dispatcher-B",))
    t1.start(); t2.start(); t1.join(); t2.join()
    ok = sum(1 for v in results.values() if v)
    print(f"  结果: {ok} 个成功 —— 必须恰好是 1 (多抢=数据竞争, 少抢=丢任务)")
    assert ok == 1, "CAS 原子认领失败!"
    # 收尾: 抢到的人把它 complete, 事件流完整收场
    c = kb.open_db(DB)
    kb.complete_task(c, tid, result="CAS 演示: 并发抢单唯一胜者完成")
    show_task(c, tid)
    c.close()


def scene_a2_lifecycle(conn):
    banner("A2  单任务完整生命周期: 建卡 -> 认领 -> 干 -> 交卷")
    tid = kb.create_task(conn, "调研 DeepSeek 蒸馏, 输出500字摘要", assignee="researcher")
    status_line(conn, tid)                      # ready: 无父任务, 建卡即可认领
    r = tick(conn)                              # tick: 认领 + spawn worker
    print(f"  tick#1: {r}")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)        # 等 worker 干完
    status_line(conn, tid)                      # done
    show_task(conn, tid)


def scene_b_pipeline(conn):
    banner("B  父依赖接力: 父任务 done, 子任务才升 ready")
    p = kb.create_task(conn, "调研 RAG 评估指标", assignee="researcher")
    c = kb.create_task(conn, "按调研结果写评估脚本", assignee="coder", parents=[p])
    status_line(conn, p)                        # ready
    status_line(conn, c)                        # todo —— 父没 done, 只能排队
    r1 = tick(conn)
    print(f"  tick#1: {r1}  (只派了父任务)")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)
    status_line(conn, c)                        # 仍是 todo
    r2 = tick(conn)
    print(f"  tick#2: {r2}  (父 done -> 子 promoted -> 又派了子任务)")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)
    status_line(conn, p)
    status_line(conn, c)
    show_task(conn, c)


def scene_c1_crash_recovery(conn):
    banner("C1  崩溃恢复: worker 被杀死, dispatcher 回收重派")
    tid = kb.create_task(conn, "写周报并发送", assignee="ops")
    r1 = tick(conn, mode="crash")               # worker 干活到一半自杀
    print(f"  tick#1: {r1}")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)
    status_line(conn, tid)                      # running —— 僵尸状态
    r2 = tick(conn)                             # 下一 tick 发现 pid 死了
    print(f"  tick#2: {r2}  (crashed -> 回收 -> 重新认领 -> 重新 spawn)")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)
    status_line(conn, tid)                      # done —— 第二次尝试成功
    show_task(conn, tid)


def scene_c2_protocol_violation(conn):
    banner("C2  协议违规熔断: worker 三次忘了交卷, dispatcher 不再重派")
    tid = kb.create_task(conn, "生成每日简报", assignee="ops")
    for i in range(1, 4):
        r = tick(conn, mode="forget")           # 干净退出, 但没 complete
        print(f"  第{i}次重派: {r}")
        time.sleep(WORK_SECONDS * 2.5 + 0.5)
        t = kb.get_task(conn, tid)
        print(f"    当前 status = {t['status']}")
    r = tick(conn, max_spawn=0)                 # 收尾 tick: 只检测不派工
    print(f"  熔断检测(不派工): {r}")
    show_task(conn, tid)                        # 最终 blocked + auto_blocked 事件
    print("  → 任务被熔断进 blocked, 等人来看 (防止 cron 无限重派空转)")


def scene_d_human_in_loop(conn):
    banner("D  人在环: worker 卡住等人, 人评论 + unblock 复活")
    tid = kb.create_task(conn, "实现登录鉴权模块", assignee="coder")
    r1 = tick(conn, mode="block")               # worker 干一半 block(needs_input)
    print(f"  tick#1: {r1}")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)
    status_line(conn, tid)                      # blocked
    kb.add_comment(conn, tid, "human", "用方案B, 别用方案A —— 理由: 兼容老客户端")
    print("  人: add_comment + unblock")
    kb.unblock_task(conn, tid)
    status_line(conn, tid)                      # ready
    r2 = tick(conn)                             # 重新派工
    print(f"  tick#2: {r2}")
    time.sleep(WORK_SECONDS * 2.5 + 0.5)
    show_task(conn, tid)                        # done, 评论跟着审计记录一起留档


# ---------------------------------------------------------------------------

def main():
    if os.path.exists(DB):
        os.remove(DB)                           # 每次重跑都是干净看板
    conn = kb.open_db(DB)
    print("Hermes Kanban 原理演示 (demo_kanban.db, 独立于你的真实看板)\n"
          f"worker 干活时长: {WORK_SECONDS}s/步 (环境变量 KANBAN_DEMO_WORK_SECONDS 可调)")
    scene_a1_cas(conn)
    scene_a2_lifecycle(conn)
    scene_b_pipeline(conn)
    scene_c1_crash_recovery(conn)
    scene_c2_protocol_violation(conn)
    scene_d_human_in_loop(conn)
    banner("收工")
    print("全部场景通过。看板文件: demo_kanban.db (可 sqlite3 打开查看)")
    print("源码对照表见 README.md")


if __name__ == "__main__":
    main()
