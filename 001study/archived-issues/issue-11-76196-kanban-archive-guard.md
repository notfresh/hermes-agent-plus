# Issue 11：kanban archive 无守卫，把正在跑的 worker 变成孤儿

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/76196
> 状态：🔴 已撞车（PR #76378 webtecnica，见下方「撞车追踪」）；🟢 干净候选阶段（无认领、无评论、无关联 PR，2026-08-02 03:02 第二次核查；07-31T13:52 创建，19 小时无人碰）
> 标签：type/bug, comp/cron, P3, sweeper:risk-session-state
> ✅ 补丁已写好并本地验证通过（2026-08-02 03:10）：`001study/scripts/fix-76196-kanban-archive-guard.patch`，2 新测试 + 4 存量 archive 测试全过

## 一句话

`hermes kanban archive <task_id>` 对**正在 running、claim 还活着**的任务直接归档：数据库里 claim 被清空，但 worker 进程没人通知，它继续跑，最后的 `complete`/`block` 交接被静默丢弃 —— 任务与工人失联。

## Premise 验证（本地代码实锤）

`hermes_cli/kanban_db.py:5542 archive_task()` 的 UPDATE 只挡 `status != 'archived'`，不挡 running：

```python
def archive_task(conn, task_id) -> bool:
    with write_txn(conn):
        cur = conn.execute(
            "UPDATE tasks SET status = 'archived', "
            "    claim_lock = NULL, claim_expires = NULL, worker_pid = NULL "  # ← 活 claim 直接清掉
            "WHERE id = ? AND status != 'archived'",
            (task_id,),
        )
        ...
        run_id = _end_run(conn, task_id, outcome="reclaimed", status="reclaimed",
                          summary="task archived with run still active")
        _append_event(conn, task_id, "archived", None, run_id=run_id)
    recompute_ready(conn)
    return True
```

`_end_run(... "reclaimed")` 只是给 attempt 历史盖了个章，**没有任何 SIGTERM / 通知机制**。worker 端（dispatcher 派生的子进程）不知道任务已被归档，继续跑完再 `kanban_complete` —— 但任务已是 archived，交接无效，worker 的产出静默丢失。issue 还指出：dashboard 里也能触发（`_cmd_archive` 的注释自己承认"user archived a running task from the dashboard"）。

## 为什么是"应该修"

- **状态机漏洞**：archive 应该只对 `todo/blocked/done` 生效，running 是"有主"状态，必须先 stop/block 才能归档。
- **修复极小**：一个 SELECT 守卫 + 一行错误提示。
- **本地可测**：临时 sqlite DB 单测，无需任何外部服务。

## 修复方案（★☆☆ 简单，1 函数 + 1 测试）

`archive_task()` 在 UPDATE 前先查状态，running + 活 claim 直接拒绝：

```python
row = conn.execute(
    "SELECT status, claim_lock FROM tasks WHERE id = ?", (task_id,)
).fetchone()
if not row or row["status"] == "archived":
    return False
if row["status"] == "running" and row["claim_lock"] is not None:
    raise ValueError(
        f"task {task_id} is running with a live claim — stop or block it before archiving"
    )  # 或返回带错误信息的 tuple，让 _cmd_archive 打印友好提示
```

配套：`_cmd_archive`（kanban.py:2173）捕获该错误打印 `cannot archive <id>: task is running (live claim)`；测试覆盖 running/blocked/done/archived 四种状态。

## ✅ 已落地补丁（03:10 本地验证通过）

补丁文件：`001study/scripts/fix-76196-kanban-archive-guard.patch`（103 行，3 文件）

**设计要点（比草稿更稳的两处）：**

1. **用 `claim_expires` 区分"活 claim"和"过期 claim"**：`status='running' AND claim_lock IS NOT NULL AND (claim_expires IS NULL OR claim_expires > now)` 才拒绝。过期 claim（worker 已消失，dispatcher 下个 tick 也会回收）允许归档——避免把"回收竞态"变成"永久无法归档"。
2. **SELECT→UPDATE 无 TOCTOU 竞态**：整个函数在 `write_txn`（BEGIN IMMEDIATE，串行化写者）内，dispatcher 的 claim 路径也走 write_txn，两者互斥，守卫不会被夹在中间绕过。
3. **ValueError 在 `write_txn` 内抛出 → 自动 ROLLBACK**（contextmanager 的 except 分支），未写任何数据，任务原样保留。

**测试（2 个新测试，全部通过）：**

- `test_archive_refuses_running_task_with_live_claim`：claim 后归档 → `pytest.raises(ValueError)`，且任务仍 running、claim_lock 原样
- `test_archive_allows_running_task_with_stale_claim`：手动把 claim_expires 拨到过去 60s，归档成功

**验证命令：** `scripts/run_tests.sh tests/hermes_cli/test_kanban_db.py -k "archive"` → 6 过 0 败（4 存量 + 2 新增）

**提 PR 前的最后一步：** 基于 upstream main 最新 commit rebase（本地快照 124f68a84 可能落后），重跑测试，然后 `git push` 到 fork + 开 PR 指向 #76196。

## 风险点

- 别改成"直接 SIGTERM worker"——进程回收链复杂（worker 可能是远程/容器），issue 要的是**守卫**，先拒绝再让用户显式 stop。
- `_end_run(outcome="reclaimed")` 逻辑保留（对历史上已在飞的 run 仍有用），只是不让新归档发生在活 claim 上。
- 注意 dispatcher 的 stale-claim 回收（默认 60s tick）与归档的竞态：守卫读到的 claim 可能刚过期——用 `claim_expires` 一起判断更稳。

---

## 撞车追踪（PR #76378）

- **08-01T19:52Z** webtecnica 提 PR #76378（fix/76196-kanban-archive-guard，+224/-9）：archive refusal/force + worker termination + closed-run heartbeat guard + explicit-heartbeat claim-loss 处理
- **08-01T19:59Z** teknium1 review（COMMENTED）：`worker_pid` 只对 host-local `claim_lock` 有意义——`_terminate_reclaimed_worker` 故意拒绝 remote locks，本地探针在远程/容器 worker 场景会误判
- **08-01T20:11Z** teknium1 加标签；**08-01T20:47Z** GottZ AI triage cross-ref：确认 PR 未完全消除孤儿 worker 路径
- **08-03 复查（本记录）**：issue 仍 open（无 assignee）；PR #76378 仍 open 未 merge，mergeable_state=unknown；自 08-01T20:11Z 后 ~32h 无任何新动态（无 author 回复/新 commit/review）。全仓库仅此 1 个 PR 引用 #76196，无竞争 PR。本地补丁作废存档维持。
- 注：teknium1 指出的远程 lock 误判点，本地补丁用 `claim_expires` 判断活 claim、不碰 worker_pid，天然绕开了该 review 意见——但按用户决策③（只攒状态不推荐），不推进。

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/76196
