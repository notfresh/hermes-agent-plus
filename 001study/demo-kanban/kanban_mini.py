#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kanban_mini.py — Hermes Kanban 核心原理的最小可运行复刻
========================================================

对照真实源码: hermes_cli/kanban_db.py (~9200 行) + gateway/kanban_watchers.py
本文件保留原理骨架, 删去多板 / 租户 / 附件 / 通知 / 工作区类型等外围,
只留五根柱子:

  1. SQLite 持久化    — 任务 / 依赖链 / 评论 / 事件 / 运行记录 五张表
  2. 状态机           — triage -> todo -> ready -> running -> done/blocked -> archived
  3. CAS 原子认领     — claim 是"带 WHERE 条件的 UPDATE", 天然并发安全
  4. 笨 dispatcher    — 每 tick 五步: 回收过期 -> 检测崩溃 -> 提升ready -> 认领 -> spawn
  5. worker=独立进程  — subprocess 拉起, 环境变量传任务ID, 双方只通过 SQLite 对话
                        (回应 NanoClaw 进程内 subagent swarm 翻车的教训)

纯教学代码, 不依赖 Hermes 本体。跑:  python3 demo_run.py
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager

# 与真实实现一致的关键常量 (真实值见 kanban_db.py / gateway 配置)
DEFAULT_CLAIM_TTL_SECONDS = 4 * 3600      # 认领 TTL: 4 小时
STALE_HEARTBEAT_SECONDS = 3600           # 心跳阈值: 1 小时无心跳视为失联
DEFAULT_FAILURE_LIMIT = 2                # 连续 spawn 失败上限, 熔断自动 block
PROTOCOL_VIOLATION_LIMIT = 3             # worker 干净退出却没 complete 的容忍次数

VALID_STATUSES = ("triage", "todo", "ready", "running", "blocked", "done", "archived")
VALID_BLOCK_KINDS = ("needs_input", "capability", "transient", "dependency")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id                   TEXT PRIMARY KEY,
    title                TEXT NOT NULL,
    body                 TEXT,
    assignee             TEXT,
    status               TEXT NOT NULL,
    priority             INTEGER DEFAULT 0,
    created_at           INTEGER NOT NULL,
    started_at           INTEGER,
    completed_at         INTEGER,
    workspace_path       TEXT,
    claim_lock           TEXT,
    claim_expires        INTEGER,
    result               TEXT,
    worker_pid           INTEGER,
    last_heartbeat_at    INTEGER,
    current_run_id       INTEGER,
    block_kind           TEXT,
    block_recurrences    INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS task_links (
    parent_id  TEXT NOT NULL,
    child_id   TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);
CREATE TABLE IF NOT EXISTS task_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL,
    run_id     INTEGER,
    kind       TEXT NOT NULL,
    payload    TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT NOT NULL,
    profile          TEXT,
    status           TEXT NOT NULL,
    claim_lock       TEXT,
    claim_expires    INTEGER,
    started_at       INTEGER,
    ended_at         INTEGER
);
"""


def now() -> int:
    return int(time.time())


def _new_id() -> str:
    return f"t_{uuid.uuid4().hex[:8]}"


def open_db(path: str) -> sqlite3.Connection:
    """打开看板数据库。

    真实实现同样用 WAL + busy_timeout: 读写在 WAL 下互不阻塞,
    写者之间靠 busy_timeout 排队而不是立刻报错。
    """
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None            # autocommit; 事务用 write_txn 显式控制
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA_SQL)
    return conn


@contextmanager
def write_txn(conn):
    """对照真实 kanban_db.py 的 write_txn: BEGIN IMMEDIATE 写事务。

    IMMEDIATE 在第一条语句时就获取写锁, 让其他写者排队等待,
    而不是像 DEFERRED 那样到写数据那一刻才升级锁 (容易死锁)。
    读者不受影响 (WAL 下读写并行)。
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _append_event(conn, task_id: str, kind: str, payload: dict, run_id=None):
    conn.execute(
        "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, run_id, kind, json.dumps(payload, ensure_ascii=False), now()),
    )


def _parents_done(conn, task_id: str) -> bool:
    """该任务的所有父任务是否都已 done (依赖门)。"""
    row = conn.execute(
        "SELECT 1 FROM task_links l JOIN tasks p ON p.id = l.parent_id "
        "WHERE l.child_id = ? AND p.status NOT IN ('done', 'archived') LIMIT 1",
        (task_id,),
    ).fetchone()
    return row is None


def _children_of(conn, task_id: str) -> list:
    return [r["child_id"] for r in conn.execute(
        "SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,))]


# ---------------------------------------------------------------------------
# 任务 CRUD
# ---------------------------------------------------------------------------

def create_task(conn, title, body="", assignee=None, parents=(), triage=False,
                priority=0) -> str:
    """
    对照 kanban_db.py:2721 create_task()

    默认状态规则 (真实源码 2748 行):
      - triage=True          -> 强制 triage (等"说明员"把规格补全)
      - 有父任务且未全部 done -> todo (排队等父)
      - 否则                 -> ready (立即可认领)
    """
    task_id = _new_id()
    for p in parents:
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (p,)).fetchone():
            raise ValueError(f"unknown parent task: {p}")
    if triage:
        status = "triage"
    elif parents and not all(conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (p,)).fetchone()["status"] == "done"
            for p in parents):
        status = "todo"
    else:
        status = "ready"
    with write_txn(conn):
        conn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, priority, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, title, body, assignee, status, priority, now()),
        )
        for p in parents:
            conn.execute(
                "INSERT INTO task_links (parent_id, child_id) VALUES (?, ?)", (p, task_id))
        _append_event(conn, task_id, "created",
                      {"title": title, "assignee": assignee, "status": status})
    return task_id


def get_task(conn, task_id: str):
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(conn, status=None):
    q = "SELECT * FROM tasks"
    args = ()
    if status:
        q += " WHERE status = ?"
        args = (status,)
    return [dict(r) for r in conn.execute(q + " ORDER BY created_at ASC", args)]


def add_comment(conn, task_id: str, author: str, body: str):
    """对照 kanban_db.py:2923 add_comment() —— 人在环的入口。"""
    if not conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
        raise ValueError(f"unknown task {task_id}")
    with write_txn(conn):
        conn.execute(
            "INSERT INTO task_comments (task_id, author, body, created_at) "
            "VALUES (?, ?, ?, ?)",
            (task_id, author, body, now()),
        )
        _append_event(conn, task_id, "commented", {"author": author, "len": len(body)})


def list_comments(conn, task_id: str):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,))]


# ---------------------------------------------------------------------------
# 认领 / 完成 / 阻塞 —— 状态机的心脏
# ---------------------------------------------------------------------------

def claim_task(conn, task_id: str, claimer: str = "dispatcher",
               ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS):
    """
    对照 kanban_db.py:3484 claim_task()

    核心是那条 CAS (Compare-And-Swap) UPDATE:
      UPDATE tasks SET status='running', claim_lock=?, ...
      WHERE id = ? AND status = 'ready' AND claim_lock IS NULL
    多个 dispatcher 同时抢同一个任务, SQLite 保证只有一个 UPDATE 命中
    (rowcount == 1), 这就是"原子认领"。没有锁表, 没有互斥量。

    前置检查: 若父任务未全部 done, 降级回 todo 并拒绝认领 ——
    这是依赖不变量的唯一强制点 (真实源码 3500-3524 行, 含一次线上事故的 RCA)。
    """
    expires = now() + ttl_seconds
    with write_txn(conn):
        if not _parents_done(conn, task_id):
            conn.execute("UPDATE tasks SET status = 'todo' WHERE id = ? AND status = 'ready'",
                         (task_id,))
            _append_event(conn, task_id, "claim_rejected", {"reason": "parents_not_done"})
            return None
        cur = conn.execute(
            "UPDATE tasks SET status = 'running', claim_lock = ?, claim_expires = ?, "
            "started_at = COALESCE(started_at, ?) "
            "WHERE id = ? AND status = 'ready' AND claim_lock IS NULL",
            (claimer, expires, now(), task_id),
        )
        if cur.rowcount != 1:
            return None  # 已被别人抢走
        task = get_task(conn, task_id)
        cur = conn.execute(
            "INSERT INTO task_runs (task_id, profile, status, claim_lock, claim_expires, "
            "started_at) VALUES (?, ?, 'running', ?, ?, ?)",
            (task_id, task["assignee"], claimer, expires, now()),
        )
        run_id = cur.lastrowid
        conn.execute("UPDATE tasks SET current_run_id = ? WHERE id = ?", (run_id, task_id))
        _append_event(conn, task_id, "claimed",
                      {"lock": claimer, "expires": expires, "run_id": run_id}, run_id=run_id)
    task["current_run_id"] = run_id
    return task


def complete_task(conn, task_id: str, result: str, run_id=None):
    """对照 kanban_db.py complete_task() —— worker 的结案协议。"""
    task = get_task(conn, task_id)
    if task is None or task["status"] != "running":
        raise ValueError(f"task {task_id} not in running (status={task and task['status']})")
    with write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status = 'done', result = ?, completed_at = ?, "
            "claim_lock = NULL, claim_expires = NULL, worker_pid = NULL "
            "WHERE id = ?",
            (result, now(), task_id),
        )
        _close_run(conn, task_id, "completed", run_id or task["current_run_id"])
        _append_event(conn, task_id, "completed", {"result_len": len(result)},
                      run_id=run_id or task["current_run_id"])


def block_task(conn, task_id: str, reason: str, kind: str = "needs_input"):
    """
    对照 kanban_db.py block_task()

    kind=dependency 时"卡在等父任务", 归队 todo, 父 done 后自动升 ready;
    其他 kind 是"卡住等人", 进 blocked。同 kind 反复 block 会被计次,
    达到 PROTOCOL_VIOLATION_LIMIT 时进 triage —— 防止 cron 无限 unblock
    空转 (真实源码 block_recurrences 注释, 1173-1178 行)。
    """
    task = get_task(conn, task_id)
    if task is None or task["status"] != "running":
        raise ValueError(f"task {task_id} not in running")
    recurrences = task["block_recurrences"] or 0
    if kind == "dependency":
        new_status = "todo"
    elif kind == task["block_kind"] and task["block_kind"] is not None:
        recurrences += 1
        new_status = "triage" if recurrences >= PROTOCOL_VIOLATION_LIMIT else "blocked"
    else:
        recurrences = 0
        new_status = "blocked"
    with write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status = ?, block_kind = ?, block_recurrences = ?, "
            "claim_lock = NULL, claim_expires = NULL, worker_pid = NULL, "
            "last_heartbeat_at = NULL WHERE id = ?",
            (new_status, kind, recurrences, task_id),
        )
        _close_run(conn, task_id, "blocked", task["current_run_id"])
        _append_event(conn, task_id, "blocked",
                      {"kind": kind, "reason": reason, "to": new_status})


def unblock_task(conn, task_id: str):
    """
    对照 kanban_db.py unblock_task()
    只可能落到 ready (父全 done) 或 todo (父还开着); 绝不回 triage。
    block_recurrences 刻意保留 —— 只有 complete 成功才清零。
    """
    status = "ready" if _parents_done(conn, task_id) else "todo"
    with write_txn(conn):
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        _append_event(conn, task_id, "unblocked", {"to": status})


def heartbeat(conn, task_id: str):
    """对照 kanban_db.py heartbeat —— 纯副作用, 证明 worker 还活着。"""
    with write_txn(conn):
        conn.execute("UPDATE tasks SET last_heartbeat_at = ? WHERE id = ?",
                     (now(), task_id))


def _close_run(conn, task_id: str, status: str, run_id):
    if run_id:
        conn.execute(
            "UPDATE task_runs SET status = ?, ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (status, now(), run_id))


# ---------------------------------------------------------------------------
# Dispatcher —— 一个"笨"的循环, 每 tick 五步
# ---------------------------------------------------------------------------

class DispatchResult:
    def __init__(self):
        self.reclaimed = []       # TTL 过期的认领
        self.stale = []           # 心跳失联
        self.crashed = []         # 进程死掉
        self.protocol_violations = []
        self.auto_blocked = []
        self.promoted = []        # todo -> ready
        self.spawned = []         # 本次拉起的新 worker

    def __repr__(self):
        return (f"DispatchResult(reclaimed={self.reclaimed}, stale={self.stale}, "
                f"crashed={self.crashed}, protocol_violations={self.protocol_violations}, "
                f"promoted={self.promoted}, spawned={self.spawned}, "
                f"auto_blocked={self.auto_blocked})")


def _release_stale_claims(conn, result):
    """TTL 过期: claim_expires 到了但任务还在 running -> 收回来重派。"""
    rows = conn.execute(
        "SELECT id, claim_lock FROM tasks "
        "WHERE status = 'running' AND claim_expires IS NOT NULL AND claim_expires < ?",
        (now(),)).fetchall()
    with write_txn(conn):
        for r in rows:
            conn.execute(
                "UPDATE tasks SET status = 'ready', claim_lock = NULL, claim_expires = NULL, "
                "worker_pid = NULL WHERE id = ? AND status = 'running'", (r["id"],))
            _append_event(conn, r["id"], "reclaimed", {"why": "ttl_expired"})
            result.reclaimed.append(r["id"])


def _detect_stale_heartbeat(conn, result, stale_seconds):
    """心跳失联: 1 小时没心跳的 running 任务, 假定 worker 卡死。"""
    cutoff = now() - stale_seconds
    rows = conn.execute(
        "SELECT id FROM tasks WHERE status = 'running' AND "
        "(last_heartbeat_at IS NULL OR last_heartbeat_at < ?)", (cutoff,)).fetchall()
    with write_txn(conn):
        for r in rows:
            conn.execute(
                "UPDATE tasks SET status = 'ready', claim_lock = NULL, claim_expires = NULL, "
                "worker_pid = NULL WHERE id = ? AND status = 'running'", (r["id"],))
            _append_event(conn, r["id"], "reclaimed", {"why": "stale_heartbeat"})
            result.stale.append(r["id"])


def _detect_crashed_workers(conn, result, failure_limit):
    """进程死了: worker_pid 对应的 OS 进程不存在了 -> 回收。

    真实实现还区分两种情况 (gateway 的协议违规机制):
      - 非零退出 / 被信号杀 -> crash, 直接回收重派
      - 退出码 0 却没调用 complete/block -> 协议违规 (worker 忘了交卷),
        连续 PROTOCOL_VIOLATION_LIMIT 次后熔断 auto-block, 防止无限重派空转。
        (真实源码是独立常量 _PROTOCOL_VIOLATION_FAILURE_LIMIT, 与 spawn
        失败熔断的 failure_limit 不是同一个数)
    """
    for task in list_tasks(conn, status="running"):
        pid = task["worker_pid"]
        if pid is None:
            continue
        if _pid_alive(pid):
            continue
        exit_code = _pid_exit_code(pid)
        with write_txn(conn):
            conn.execute(
                "UPDATE tasks SET status = 'ready', claim_lock = NULL, "
                "claim_expires = NULL, worker_pid = NULL WHERE id = ?", (task["id"],))
            if exit_code == 0:
                fails = (task["consecutive_failures"] or 0) + 1
                if fails >= PROTOCOL_VIOLATION_LIMIT:
                    conn.execute(
                        "UPDATE tasks SET status = 'blocked', consecutive_failures = ? "
                        "WHERE id = ?", (fails, task["id"]))
                    _append_event(conn, task["id"], "auto_blocked",
                                  {"why": "protocol_violation", "fails": fails})
                    result.auto_blocked.append(task["id"])
                else:
                    conn.execute("UPDATE tasks SET consecutive_failures = ? WHERE id = ?",
                                 (fails, task["id"]))
                    _append_event(conn, task["id"], "protocol_violation", {"fails": fails})
                    result.protocol_violations.append(task["id"])
            else:
                conn.execute("UPDATE tasks SET consecutive_failures = 0 WHERE id = ?",
                             (task["id"],))
                _append_event(conn, task["id"], "crashed", {"exit": exit_code})
                result.crashed.append(task["id"])


def _recompute_ready(conn, result):
    """依赖晋升: 父任务全部 done 的 todo 任务 -> ready。"""
    rows = conn.execute("SELECT id FROM tasks WHERE status = 'todo'").fetchall()
    with write_txn(conn):
        for r in rows:
            if _parents_done(conn, r["id"]):
                conn.execute("UPDATE tasks SET status = 'ready' WHERE id = ?", (r["id"],))
                _append_event(conn, r["id"], "promoted", {"why": "parents_done"})
                result.promoted.append(r["id"])


def dispatch_once(conn, spawn_fn=None, *, claim_ttl=DEFAULT_CLAIM_TTL_SECONDS,
                  stale_seconds=STALE_HEARTBEAT_SECONDS, failure_limit=DEFAULT_FAILURE_LIMIT,
                  max_spawn=4, claimer="dispatcher") -> DispatchResult:
    """
    对照 kanban_db.py:7439 dispatch_once() —— 一个 tick 的全部内容。

    真实源码的 tick 顺序 (docstring 7521-7529 行):
      1. 回收 TTL 过期的认领 (release_stale_claims)
      2. 回收心跳失联的 running (detect_stale_running)
      3. 回收进程已死的 running (detect_crashed_workers)
      4. 晋升 todo -> ready (父全 done)
      5. 对每个 ready 任务: CAS 原子认领, 然后 spawn_fn(task) 拉起 worker 进程

    顺序很重要: 先回收再晋升再认领, 一个 tick 内完成"清扫 -> 放行 -> 派工"。
    spawn 失败按任务累计, 连续 failure_limit 次 -> 熔断自动 block (防抖动)。
    """
    # Reap zombie children from previously spawned workers. 真实源码
    # kanban_db.py 7547-7549 行同样在每个 tick 开头做这一步 —— 不收尸的话
    # 僵尸进程会让 os.kill(pid, 0) 误报"还活着", 崩溃检测形同虚设。
    reap_worker_zombies()
    result = DispatchResult()
    _release_stale_claims(conn, result)
    _detect_stale_heartbeat(conn, result, stale_seconds)
    _detect_crashed_workers(conn, result, failure_limit)
    _recompute_ready(conn, result)

    running = sum(1 for t in list_tasks(conn, status="running"))
    ready_rows = conn.execute(
        "SELECT id, assignee FROM tasks WHERE status = 'ready' AND claim_lock IS NULL "
        "ORDER BY priority DESC, created_at ASC").fetchall()
    for r in ready_rows:
        if running >= max_spawn:
            break  # 并发上限 (真实源码 7583-7589 行的 live cap 语义)
        task = claim_task(conn, r["id"], claimer=claimer, ttl_seconds=claim_ttl)
        if task is None:
            continue
        if spawn_fn is None:
            result.spawned.append(task["id"])
            continue
        try:
            pid = spawn_fn(task)  # 返回 worker 进程 PID
            with write_txn(conn):
                conn.execute("UPDATE tasks SET worker_pid = ? WHERE id = ?",
                             (pid, task["id"]))
                _append_event(conn, task["id"], "spawned", {"pid": pid},
                              run_id=task["current_run_id"])
            result.spawned.append(task["id"])
            running += 1
        except Exception as e:  # spawn 失败 -> 熔断计数
            fails = (task["consecutive_failures"] or 0) + 1
            with write_txn(conn):
                conn.execute(
                    "UPDATE tasks SET status = 'ready', claim_lock = NULL, "
                    "claim_expires = NULL, worker_pid = NULL, consecutive_failures = ? "
                    "WHERE id = ?", (fails, task["id"]))
                _append_event(conn, task["id"], "spawn_failed", {"err": str(e)})
                if fails >= failure_limit:
                    conn.execute("UPDATE tasks SET status = 'blocked' WHERE id = ?",
                                 (task["id"],))
                    _append_event(conn, task["id"], "auto_blocked",
                                  {"why": "spawn_failure", "fails": fails})
                    result.auto_blocked.append(task["id"])
    return result


# ---------------------------------------------------------------------------
# Worker 进程生命周期 (供 dispatcher 用)
# ---------------------------------------------------------------------------

# 模块级进程注册表: pid -> 收尸时记录的退出码。
# 与真实实现一致: 每个 tick 开头 reap 一次僵尸 (kanban_db.py 7547-7549 行),
# 否则 os.kill(pid, 0) 对僵尸进程仍返回成功, 崩溃检测永远发现不了死 worker。
_EXIT_CODES = {}


def reap_worker_zombies():
    """收尸: 把已退出的子进程 waitpid 掉, 记录退出码, 防止僵尸堆积。"""
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break                          # 没有子进程了
        if pid == 0:
            break                          # 没有已退出的子进程
        _EXIT_CODES[pid] = os.waitstatus_to_exitcode(status)


def spawn_worker(task: dict, worker_script: str, workspace_root: str,
                 python=None, extra_args=()) -> int:
    """
    对照真实 dispatcher 的 spawn 逻辑: 用 subprocess 拉起一个"完整 OS 进程",
    通过环境变量 HERMES_KANBAN_TASK / HERMES_KANBAN_WORKSPACE 传任务上下文,
    而不是进程内函数调用 —— 这就是"每个 worker 是完整进程"的设计。
    extra_args 透传给 worker 命令行 (demo 里用于切换 worker 行为模式)。
    """
    ws = os.path.join(workspace_root, task["id"])
    os.makedirs(ws, exist_ok=True)
    env = dict(os.environ)
    env["HERMES_KANBAN_TASK"] = task["id"]
    env["HERMES_KANBAN_WORKSPACE"] = ws
    env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.Popen([python or sys.executable, worker_script, *extra_args],
                            env=env, stdout=None, stderr=None)  # 日志透传, 教学可见
    return proc.pid


# ---------------------------------------------------------------------------
# 进程存活探测 (Linux)
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _pid_exit_code(pid: int) -> int:
    """pid 已死时捞退出码; 捞不到按非零处理 (视为 crash)。

    与真实实现一致: 退出码 0 但任务没 complete -> 协议违规 (worker 忘了交卷);
    非零退出 -> 视为 crash。退出码来自 tick 开头的 reap_worker_zombies()
    (真实里 gateway 是 worker 的父进程, 直接 waitpid)。
    """
    return _EXIT_CODES.get(pid, 1)
