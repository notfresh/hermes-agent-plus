# Kanban 原理 Demo（001study/kanban-demo）

用最小 Python 代码复刻 Hermes Kanban 的核心机制。纯标准库，无第三方依赖，
不碰你的真实看板（`~/.hermes/kanban.db`），跑的是自己的 `demo_kanban.db`。

```bash
python3 demo_run.py        # 跑全部 6 个场景, 约 20 秒
python3 demo_run.py 2>&1 | head -60   # 只看 A1 (CAS 并发抢单)
```

文件清单：

| 文件 | 对应真实源码 | 内容 |
|------|--------------|------|
| `kanban_mini.py` | `hermes_cli/kanban_db.py` (~9200 行) | 核心库：schema、状态机、CAS 认领、dispatcher tick |
| `demo_worker.py` | `tools/kanban_tools.py` + worker 生命周期 | worker 进程：show→干活→心跳→complete/block |
| `demo_run.py` | gateway 里每 60s 的 `dispatch_once` | 6 个教学场景剧本 |

---

## 一、五根柱子（对照源码）

### 1. SQLite 持久化 —— 任务 / 依赖 / 评论 / 事件 / 运行

五张表（`kanban_mini.py` SCHEMA_SQL ↔ `kanban_db.py:1096` SCHEMA_SQL）：

- `tasks`：任务行。状态、assignee、认领锁(claim_lock/claim_expires)、
  worker_pid、最后心跳、连续失败计数、block 循环计数……全在一行里
- `task_links`：父子依赖（parent_id, child_id）
- `task_comments`：人在环的批注
- `task_events`：审计轨迹，每个状态变化一条事件（created/claimed/spawned/
  completed/crashed/blocked/...），永远不删
- `task_runs`：每次认领一条历史，重试后一个任务有多条 run

### 2. 状态机

```
triage -> todo -> ready -> running -> done / blocked -> archived
              \___________/          （阻塞后可 unblock 回 ready/todo）
```

create 默认状态规则（`kanban_mini.py` create_task ↔ `kanban_db.py:2748`）：
无父任务 → `ready`；父任务没全 done → `todo`；`triage=True` → `triage`。

### 3. CAS 原子认领 —— 并发安全的全部秘密

`claim_task`（↔ `kanban_db.py:3484`）的核心是一条带 WHERE 的 UPDATE：

```sql
UPDATE tasks SET status='running', claim_lock=?, claim_expires=?
WHERE id = ? AND status='ready' AND claim_lock IS NULL
```

多个 dispatcher 同时抢，SQLite 保证恰好一个 UPDATE 命中（rowcount==1）。
**没有锁表、没有互斥量**。场景 A1 用两个线程 + Barrier 对齐起跑线实测：
恰好 1 个成功。认领前还检查父任务（依赖不变量，真实源码 3500-3524 行，
含一次线上事故的 RCA 注释），父未 done 直接降级 `todo` 并记
`claim_rejected` 事件。

### 4. 笨 dispatcher —— 每 tick 五步

`dispatch_once`（↔ `kanban_db.py:7439`），默认 60s 一次，顺序固定：

1. `reap_worker_zombies()`  收尸（↔ 7547-7549 行）—— 不收尸的话僵尸进程
   会让 `os.kill(pid,0)` 误报"还活着"，崩溃检测形同虚设
2. `_release_stale_claims`  TTL 过期回收（认领 4h 默认）
3. `_detect_stale_heartbeat` 心跳失联回收（1h 无心跳假定卡死）
4. `_detect_crashed_workers` 进程死亡回收（区分 crash 与协议违规）
5. `_recompute_ready` 父任务全 done → 子任务 todo→ready（依赖晋升）
6. 对每个 ready 任务：CAS 认领 → spawn worker 进程

spawn 连续失败 `failure_limit` 次（默认 2）→ 熔断 auto-block，
防止对"profile 不存在"这种无解任务无限重派（↔ kanban.py 帮助文本）。

### 5. worker = 完整 OS 进程

dispatcher 用 `subprocess.Popen` 拉起 worker（↔ 真实里 `hermes chat -q`），
通过环境变量传任务：

```
HERMES_KANBAN_TASK=t_xxxx      HERMES_KANBAN_WORKSPACE=<目录>
```

worker 只通过 SQLite 与看板对话（show/complete/block/heartbeat），
**绝不 shell 出去调 CLI**。这就是设计文档（docs/hermes-kanban-v1-spec.pdf）
对 NanoClaw 翻车（进程内 subagent 随父 turn 结束被静默杀死）的回应：
协调发生在协调系统自己控制的层。

## 二、可靠性机制（场景 C1/C2/D 演示）

| 机制 | 场景 | 原理 |
|------|------|------|
| 崩溃恢复 | C1 | worker 被杀 → 僵尸 → 下个 tick reap + 回收 → 重新认领重派 |
| 协议违规熔断 | C2 | worker 退出码 0 却没 complete → 连续 3 次（真实 `_PROTOCOL_VIOLATION_FAILURE_LIMIT`）→ auto-block，防 cron 无限重派空转 |
| 人在环 | D | worker block(needs_input) → 人 comment + unblock → 任务复活重派 |
| 心跳 | 所有场景 | worker 干一半 heartbeat，防被当僵尸回收（真实：1h 无心跳回收） |
| 依赖门 | B | 认领前查父任务；todo 任务在父 done 后由 recompute_ready 自动晋升 |

## 三、简化掉的部分（真实源码有，demo 没做）

- 多板（boards）、租户（tenant）隔离 —— demo 单库单板
- 工作区三种类型（scratch 临时 / dir 共享 / worktree git）—— demo 固定目录
- 附件（attach/attachments）与通知（notify）
- 单写者 dispatch 锁（`kanban.db.dispatch.lock`）、WAL checkpoint 管理
- 任务完成时的 artifacts 声明与持久化
- 认领 TTL / 心跳阈值真实值 4h/1h，demo 场景里用短 sleep 模拟

## 四、怎么继续玩

```bash
# 加速 / 减速 worker
KANBAN_DEMO_WORK_SECONDS=0.2 python3 demo_run.py

# 直接当库用, 手动操作看板
python3 -c "
import kanban_mini as kb, os
conn = kb.open_db('/tmp/x.db')
tid = kb.create_task(conn, '手动任务', assignee='me')
print(kb.get_task(conn, tid)['status'])   # ready
kb.claim_task(conn, tid, claimer='me')
kb.complete_task(conn, tid, '搞定了')
print([e['kind'] for e in conn.execute(
    'SELECT kind FROM task_events WHERE task_id=?', (tid,))])  # 审计轨迹
"

# 用 sqlite3 直接看表
sqlite3 demo_kanban.db "SELECT id,title,status,worker_pid FROM tasks;"
sqlite3 demo_kanban.db "SELECT kind,payload FROM task_events ORDER BY id;"
```
