# Hermes 并发与任务隔离机制调查报告

> 调查时间：2026-08-10
> 调查对象：hermes-agent-plus（源码研究副本，所有行号均指向该副本）
> 目的：回答「多个流程/任务同时启动时，Hermes 如何保证互不干扰、如何隔离」；为 MinimalAgentV2 的多任务扩展提供设计依据。

---

## 0. 结论摘要（先给答案）

用户的直觉**大方向完全正确**，且遗漏了两个关键细节：

| 用户猜测 | 验证结果 |
|---------|---------|
| 会话独立存储 | ✅ 对。`sessions`/`messages` 表按 `session_id` 隔离（hermes_state.py:762/812） |
| 没有公共资源征用就天生互不影响 | ✅ 对。每会话一个独立 AIAgent 实例，内存天然隔离 |
| 各自写到各自的内存/文件/SQLite | ✅ 对。运行期在内存，`_flush_messages_to_session_db` 定期刷盘（run_agent.py:1813） |
| 任务各自刷盘即可 | ⚠️ 对了一半。**共享 DB 是单写者**：WAL 允许多读单写，写事务必须串行（BEGIN IMMEDIATE） |
| —— | ⚠️ **漏了 env 陷阱**：`TERMINAL_CWD` 是进程全局环境变量，cron 为此专门用单线程顺序池 + 读写锁保护 |

Hermes 的隔离哲学可以浓缩为一句话：

> **能自包含就自包含（每会话独立实例），非共享不可的才上锁（DB 单写者、env 串行化），锁也挡不住的用上下文拷贝（contextvars）。**

---

## 1. 顶层拓扑：三种运行形态的并发模型

Hermes 同一个核心，跑在三种形态里，并发模型不同：

### 1.1 CLI（单进程单线程）
一个 `hermes` 命令 = 一个进程 = 一个会话 = 一个 agent 实例。天然隔离，无并发问题。

### 1.2 Gateway（单进程，asyncio + 多线程）
- 主事件循环：asyncio（gateway/run.py 大量 `asyncio.create_task` / `asyncio.gather`）
- 每个平台 adapter（Telegram/Slack/飞书/……）在自己的线程/异步任务里收消息，收到后投递到主循环
- 阻塞操作丢进 `ThreadPoolExecutor`（gateway/run.py:16331-16343）
- **不同会话的消息可以并行处理**（各自 agent 实例）；**同一会话的消息串行**（busy 时排队，见 §2.3）

### 1.3 Cron（gateway 进程内的双线程池）
cron/scheduler.py 是并发设计最讲究的地方：

```
                      tick（定时触发）
                           │
            ┌──────────────┴──────────────┐
     workdir 的 job                   无 workdir 的 job
            │                              │
     顺序池 (max_workers=1)           并行池 (max_workers=N)
     "cron-seq"                       "cron-parallel"
```

- **为什么 workdir job 必须串行？** 因为 `run_job` 会写 `os.environ["TERMINAL_CWD"]`——**环境变量是进程全局的**，两个 job 同时改会互相污染（scheduler.py:3985-3992 注释原话）。
- **无 workdir 的 job 并行**，但读 TERMINAL_CWD 时用 `_ReadWriteLock`（scheduler.py:498）——workdir job 持写锁期间，并行 job 读不到中间状态。

---

## 2. 隔离机制拆解（按维度）

### 2.1 存储隔离：SQLite 按 session_id 分家

`hermes_state.py` 单文件 `state.db`，核心表：

- `sessions`（:762）：一行一个会话。id 主键 + `session_key`（平台+chat 派生）+ `chat_id`/`thread_id`/`user_id` + cwd/git 元数据 + 计费统计
- `messages`（:812）：`session_id` 外键，每行一条消息。**所有消息按会话归属**
- `compression_locks`（:871）：`session_id` 主键——**压缩锁按会话粒度**，同一会话不会同时发生两次压缩

→ 存储层隔离 = 一个 `session_id` 命名空间，查询/写入都带这个键。

### 2.2 内存隔离：每会话独立 AIAgent 实例

Gateway 用 LRU 缓存持有每个会话的 agent 实例（gateway/run.py:63-68）：

```python
_AGENT_CACHE_MAX_SIZE = 128
_AGENT_CACHE_IDLE_TTL_SECS = 3600.0  # 空闲超1h驱逐
```

每个 AIAgent 内部持有自己的：LLM clients、tool schemas、memory providers、**对话消息列表**。两个会话的 agent 实例互不共享可变状态 → **内存隔离是结构性的，不需要锁**。

保护细节：
- `_running_agents`：正在跑 turn 的 agent 不会被 LRU 驱逐（run.py:18029-18035）
- `_AGENT_PENDING_SENTINEL`：防「同会话第二条消息在异步间隙绕过 running 守卫」（run.py:2008）
- `_CONVERSATION_SCOPED_STATE`：会话边界（/new、/resume、过期）时统一清理的会话级状态清单（run.py:2010-2030）——防止上一会话的状态泄漏进下一会话

### 2.3 同会话 vs 跨会话的并发纪律

- **跨会话**：并行。每个 agent 一个 turn，互不等待
- **同会话**：串行。新消息要么排队（`busy_input_mode=queue`），要么 interrupt 当前 turn
- 每轮开始 `_init_cached_agent_for_turn` 重置 per-turn 状态（`_last_activity_ts`、`_last_flushed_db_idx`、`_api_call_count`，run.py:18053-18074）

### 2.4 上下文隔离：contextvar vs env var

Hermes 两种「工作目录」传递方式，隔离性天差地别：

| 载体 | 作用域 | 并发风险 | 用法 |
|------|--------|---------|------|
| `_SESSION_CWD` ContextVar（agent/runtime_cwd.py:23） | 线程/异步上下文 | **无**（contextvar 天然线程隔离） | 多会话 gateway 用 `set_session_cwd()` pin 逻辑 cwd |
| `TERMINAL_CWD` env var | **进程全局** | **高**（所有线程可见） | cron 启动时 bridge 一次；工具执行读取 |

cron 的解法：每个 job 提交前 `contextvars.copy_context()`，worker 里 `ctx.run(_process_job)`（scheduler.py:4025-4029）——**每个 job 在自己的上下文快照里跑**，`_SESSION_CWD` 等 contextvar 永远不会串。

### 2.5 任务级隔离（cron 维度）

- **in-flight 去重**：`_running_lock` + `_running_job_ids` 集合——同一 job 上一个 tick 还在跑，新 tick 直接跳过（scheduler.py:4016-4020）
- **执行记录**：每次运行 `create_execution()` 独立落 `executions` 表，崩溃后 recovery 分类处理、不自动重试（scheduler.py:4023）
- **会话 DB 写串行**：`_session_db_pool = ThreadPoolExecutor(max_workers=1)`（scheduler.py:2838）——多个 job 同时写会话状态不打架

### 2.6 工具执行的并发（与 teach-19 呼应）

单个 turn 内多个工具调用可以并发，但有边界：
- 并发批次：`_begin_in_order` start gate 无超时会饥饿（tool_executor.py:806-815，teach-19 已讲）
- 顺序路径有 deadline（tool_executor.py:1421）
- 工具注册世代 `registry._generation`：注册/注销时 +1，自动失效工具定义缓存

---

## 3. 共享资源征用点清单（会打架的地方）

隔离不是免费的——以下资源是**所有会话/任务共享**的，是并发 bug 的高发区：

| 共享资源 | 保护机制 | 出过的 bug（issue 证据） |
|---------|---------|------------------------|
| `state.db`（SQLite） | WAL（多读单写）+ `BEGIN IMMEDIATE` 显式事务 + `timeout=1.0` 短超时 + 应用层重试带 jitter（hermes_state.py:1065-1078） | #77775（WAL/SHM 侧文件消失误判只读）、#78182（FTS 重建失败不落盘） |
| `TERMINAL_CWD` env | 顺序池 + `_ReadWriteLock` | #79623（cron 会话 cwd 缺失——env bridge 单向性） |
| `_running_job_ids` | `threading.Lock` | #79244（job 卡 running，3 分钟中断不触发） |
| credential pool（凭据轮转） | 池条目绑定 | #79156（per-turn 刷新后 entry id 不重绑，错怪健康条目） |
| 工具定义缓存 | `registry._generation` 世代计数 | #79047（api_server 绕过缓存，每次 +3.3s） |
| LLM provider API 配额 | 应用层退避 + fallback 链 | #77305（API 失败扣迭代预算饿死 fallback） |
| prompt 缓存 | per-conversation 天然隔离 | #79602（provider 无法声明 cache 策略） |

**规律**：Hermes 能大规模并发，不是靠「消灭共享」，而是靠「精确知道哪些是共享的，然后为每一样配一种保护」。

---

## 4. 可复用的隔离方法清单（给 V2 的设计素材）

按「成本从低到高」排列，V2 可以按需选取：

1. **实例隔离**（零成本）：每任务一个独立对象实例，可变状态全在实例内——第一优先
2. **contextvar 隔离**（零成本）：线程/任务内的隐式上下文（cwd、临时覆盖）——绝不污染全局
3. **只读共享**：配置、工具定义等只读数据可共享，但要防「读一半被改」（用世代计数/不可变快照）
4. **单写者队列**：DB 写入集中到一个线程/池（scheduler.py:2838 模式）——最简单可靠
5. **读写锁**：读多写少的共享状态（TERMINAL_CWD 模式）
6. **WAL + 显式事务**：真多线程写 SQLite 的底线（多读单写 + 串行提交）
7. **运行集去重**：同一任务不重叠执行（running set + lock）
8. **快照上下文**：`copy_context()` 让每个任务在隔离的上下文里跑

---

## 5. 一句话总结

Hermes 的多任务隔离 = **存储按会话分家（SQLite session_id）+ 内存按实例分家（每会话独立 agent）+ 上下文按快照分家（contextvar copy）+ 非共享不可的资源逐个上锁（WAL/顺序池/读写锁）**。

用户的直觉（会话独立存储 + 无征用则无干扰）是这个架构的第一性原理；剩下的工程全部花在「找出那些躲不开的共享点，逐个驯服它们」。
