# 教学 5：Hermes 定时调度器 (Cron)

## 一句话

Hermes Cron 是一个 **每 60 秒一次 tick + 文件锁去重 + 并行线程池 + plugin-able 调度器 ABC** 的定时任务系统。gateway 后台线程驱动 tick，调用 `scheduler.tick()` → `run_job()` → 执行（no_agent 脚本或 full-agent LLM 任务）→ 交付结果到目标平台。

---

## 1. 文件结构（8 个文件，8292 行）

| 文件 | 行数 | 职责 |
|------|------|------|
| `cron/scheduler.py` | 4153 | tick 循环、run_job 核心、并行池、锁、超时、状态跟踪 |
| `cron/jobs.py` | 2382 | 存储 CRUD、调度计算、输出管理、心跳 |
| `cron/executions.py` | 228 | 单次执行的跟踪（创建/完成/中断恢复） |
| `cron/scheduler_provider.py` | 219 | ABC + 内置 InProcessCronScheduler |
| `cron/lifecycle_guard.py` | 141 | Gateway 生命周期命令防护 |
| `cron/suggestions.py` | 260 | 常见 cron 场景的提示模板 |
| `cron/suggestion_catalog.py` | 154 | 模板目录 |
| `cron/blueprint_catalog.py` | 713 | 自动化蓝图目录 |
| `cron/__init__.py` | 42 | 导出 API |

---

## 2. 数据流全链路

```
Gateway 后台线程 (every 60s)
  → InProcessCronScheduler.start()
    → scheduler.tick()
      [文件锁 ~/.hermes/cron/.tick.lock] ← 防并行 tick
        → get_due_jobs()   ← 读 jobs.json
        → advance_next_run() ← 先推进下次执行时间（at-most-once）
        → ThreadPoolExecutor.submit(run_job)  ← 并行执行
```

---

## 3. tick() 核心逻辑（scheduler.py:3888）

```python
def tick(verbose=True, adapters=None, loop=None, sync=True, can_dispatch=None):
    # 1. 文件锁 — 跨进程互斥
    lock_fd = open(lock_file, "w")
    fcntl.flock(lock_fd, LOCK_EX | LOCK_NB)  # LOCK_NB = 非阻塞
    
    # 2. 检查 dispatch gate（gateway 排空时跳过）
    if can_dispatch is not None and not can_dispatch():
        return 0
    
    # 3. 获取到期任务
    due_jobs = get_due_jobs()
    
    # 4. 主键：先在锁内推下次执行时间（at-most-once 语义）
    for job in due_jobs:
        advance_next_run(job["id"])
    
    # 5. 释放文件锁 → jobs 放入并行线程池
    #    支持 HERMES_CRON_MAX_PARALLEL 环境变量控制并行度
    for job in due_jobs:
        _submit_with_guard(job, adapters, loop)
```

**at-most-once 语义的关键**：在锁内先 `advance_next_run` 再释放锁，确保
- 每个 job 不会被执行两次
- 并行执行的 job 在完成后通过 `mark_job_run` 修正实际执行时间

---

## 4. run_job() — 两种执行模式（scheduler.py:2659）

### 模式 A：no_agent 脚本模式（看门狗模式）

```python
if job.get("no_agent"):
    script_path = job.get("script")
    ok, output = _run_job_script_with_claim_heartbeat(job, script_path)
    
    if not ok:
        # 脚本失败 → 交付错误通知
        return False, doc, alert, output
    
    if not _parse_wake_gate(output):
        # wakeAgent=false → 静默跳过（无交付）
        return True, silent_doc, None, None
    
    # 成功 → 交付脚本输出
    return True, doc, output, None
```

特征：
- **纯脚本执行**，0 token 消耗
- **心跳保活**：脚本执行时定期更新 rjunning claim，防止被误判为僵尸
- **wakeAgent gate**：脚本通过 `wakeAgent: true/false` 控制本次是否交付
- **空 stdout** → 静默跳过（不交付）

### 模式 B：Full-Agent 模式

```python
# 1. 构建 job prompt + 加载 skills + 确定 toolset
prompt = _build_job_prompt(job)

# 2. 构建 AIAgent（run_agent.py）
agent = build_cron_agent(prompt, job, cfg)

# 3. 注入 context_from 的上下文（上游 job 输出）
context = _load_context_from_jobs(job.get("context_from", []))

# 4. 运行 agent 循环
agent.run()

# 5. 提取最终响应
final_response = agent.results

# 6. 检测沉默标记 [SILENT] → 无交付
if _is_cron_silence_response(final_response):
    return True, doc, None, None

# 7. 交付结果
_deliver_result(job, final_response, adapters, loop)
```

---

## 5. 关键安全防护

### 5.1 工具沙箱 — cronspawn 也不能做的是这三件

```python
# scheduler.py:156-176
_disabled_cron_toolsets = ["cronjob", "messaging", "clarify"]

def _resolve_cron_disabled_toolsets(cfg):
    # cron 任务绝对不能：
    # - cronjob: 递归调度更多 cron（#safety）
    # - messaging: 交互式发消息（需要网关会话）
    # - clarify: 阻塞等待用户输入（非交互式）
    # 再加上用户配置的 agent.disabled_toolsets
```

### 5.2 Gateway 生命周期防护（lifecycle_guard.py）

```python
_GATEWAY_LIFECYCLE_PATTERN = re.compile(r"""
    (?:hermes\s+gateway\s+(?:restart|stop))    # hermes gateway restart/stop
    |(?:launchctl\s+...hermes[.\-]?gateway)     # launchd
    |(?:systemctl\s+...hermes[.\-]?gateway)     # systemctl
    |(?:p?kill\b...\bhermes\b...\bgateway)       # kill gateway
""")
```

在 job create/update 时检查 prompt + script 内容，防止 agent 创建自毁循环。

### 5.3 Prompt Injection 扫描

```python
class CronPromptInjectionBlocked(Exception):
    """在 _build_job_prompt 时扫描完整 prompt + skill 内容，
       防止恶意 skill 在运行时注入逃逸 payload。"""
```

### 5.4 跨进程文件锁

```
~/.hermes/cron/.tick.lock  — tick 级别锁 (fcntl/flock)
~/.hermes/cron/jobs.json   — jobs 文件锁 (fcntl + RLock)
```

---

## 6. Job 存储模型（jobs.json）

### 存储位置

```
~/.hermes/cron/
├── jobs.json              # 所有 job 定义（per-profile → get_hermes_home()）
├── .tick.lock             # tick 跨进程锁
├── .jobs.lock             # jobs.json 跨进程锁
├── ticker_heartbeat       # 心跳文件（检测 ticker 是否存活）
├── ticker_last_success    # 上次成功 tick 标记
└── output/{job_id}/
    ├── 2026-07-31_06-00-01.md  # 每次执行的输出
    └── ...
```

### Job 数据结构（create_job, jobs.py:1072）

```python
job = {
    "id": str(uuid.uuid4())[:12],
    "name": "任务001: Hermes Agent 探索",
    "prompt": "...",          # Agent 模式的系统提示
    "schedule": "0 6,22 * * *",  # cron 表达式 / "30m" / ISO 时间
    "repeat": None,           # None = 无限, N = 执行 N 次
    "script": None,           # no_agent 模式脚本路径
    "no_agent": False,
    "enabled_toolsets": ["web", "file"],
    "skills": ["hermes-agent"],
    "model": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    "workdir": "/root/projects/hermes-agent-plus",
    "deliver": "origin",      # 交付目标
    "context_from": ["other_job_id"],  # 上游 job 注入
    "next_run_at": "2026-07-31T06:00:00+08:00",
    "last_run_at": "2026-07-31T06:01:00+08:00",
    "last_status": "ok",
    "last_error": None,
    "run_count": 3,
    "paused": False,
    "created_at": "...",
    "updated_at": "...",
}
```

### 调度计算（croniter 库）

支持三种调度格式：
- **ISO 时间戳** — 单次执行（+120s 宽限期）
- **cron 表达式** — `"0 6,22 * * *"`（依赖 croniter 库）
- **持续时间** — `"30m"`, `"2h"`, `"every 2h"`（内部解析）

---

## 7. Profile 隔离（关键设计）

```python
# jobs.py:54-66 — 每个 profile 拥有自己的 cron store
HERMES_DIR = get_hermes_home().resolve()  # profile-aware!
CRON_DIR = HERMES_DIR / "cron"
JOBS_FILE = CRON_DIR / "jobs.json"

# 通过 use_cron_store() 上下文管理器可以重定向
with use_cron_store("/root/.hermes/profiles/coder"):
    create_job(...)  # 写到 coder 的 jobs.json
```

这意味着：
- 不同 profile 的 job 各自独立
- 执行时使用对应 profile 的 `.env`/`config.yaml`/`skills`
- 安全边界：一个 profile 的 cron 不会泄漏另一个的凭证

---

## 8. 并行执行与并发控制

- **默认并行**：unbounded（所有到期 job 同时跑）
- **配置控制**：`cron.max_parallel_jobs` 或 `HERMES_CRON_MAX_PARALLEL` 环境变量
- **串行模式**：`HERMES_CRON_MAX_PARALLEL=1` 恢复旧版串行行为
- **线程安全**：`_jobs_file_lock = threading.RLock()` 保护 jobs.json 读写
- **运行跟踪**：`_running_job_ids` set + `_running_lock` 追踪当前执行中的 job
- **中断检测**：`_interrupted_job_ids` 在 gateway 关闭时标记被强行终止的 job

---

## 9. 交付系统

```python
def _deliver_result(job, text, adapters=None, loop=None):
    # 1. 沉默标记检测
    if _is_cron_silence_response(text):
        return  # 静默
    
    # 2. 检测 attach_to_session → 创建线程/回复链
    if job.get("attach_to_session"):
        # 在 Telegram/Discord/Slack 上创建独立线程
        ...
    
    # 3. 按 deliver 目标分发
    for target in parse_delivery_targets(job["deliver"]):
        if target == "origin":
            send_back_to_origin_chat(adapters, text)
        elif target == "local":
            save_to_local_only(text)
        elif target.startswith("telegram:") or target.startswith("discord:"):
            platform_send(adapters, target, text)
        elif target == "all":
            fanout_all_platforms(adapters, text)
```

Delivery 目的地格式：`"platform:chat_id:thread_id"` 或 `"origin"` / `"local"` / `"all"`

---

## 10. 沉默标记系统（SILENT）

```python
_CRON_SILENCE_TOKENS = frozenset({
    "[SILENT]", "SILENT", "NO_REPLY", "NO REPLY"
})

def _is_cron_silence_response(text):
    # 识别规则：
    # 1. 整个响应 = 沉默标记
    # 2. 第一行或最后一行是沉默标记（独立行）
    # 3. 以 [SILENT] 开头（同行前缀）
    # 不匹配：单词中间出现（eg. "Silent retry succeeded"）
```

---

## 11. 可插拔调度器（ABC）

```python
class CronScheduler(ABC):
    @abstractmethod
    def start(self, stop_event, *, adapters=None, loop=None, interval=60):
        ...

class InProcessCronScheduler(CronScheduler):
    """内置：每 60s 后台线程 tick"""
    def start(self, ...):
        while not stop_event.is_set():
            cron_tick(...)
            stop_event.wait(interval)
```

通过 `cron.provider` 配置切换，未来可支持 Chronos 等外部调度器。

---

## 12. 发现的设计亮点

1. **at-most-once 语义** — 锁内先 advance_next_run 再释放，杜绝重复执行
2. **三段级别隔离** — toolset → lifecycle guard → prompt injection scanner
3. **Profile 级数据隔离** — 每个 profile 拥有独立 jobs.json
4. **并行线程池 + 运行跟踪** — 不阻塞 tick 循环，支持中断恢复
5. **SILENT 协议** — 节省 token 和用户注意力（无事发生不交付）
6. **no_agent short-circuit** — 0 token 消耗的看门狗模式
7. **心跳 + 僵尸检测** — ticker_heartbeat + ticker_last_success 双通道
8. **context_from 链** — 一个 job 的上次输出作为另一个的输入
9. **workdir 支持** — 每个 job 可在指定目录运行，加载其 AGENTS.md

### 关键代码位置

| 功能 | 文件 | 行号 |
|------|------|------|
| tick 入口 | `cron/scheduler.py` | 3888 |
| run_job（全量） | `cron/scheduler.py` | 2659 |
| no_agent 脚本模式 | `cron/scheduler.py` | 2699 |
| Agent 构建 + 执行 | `cron/scheduler.py` | ~2760-3700 |
| 工具沙箱过滤 | `cron/scheduler.py` | 156-176 |
| Job CRUD | `cron/jobs.py` | 1072-1475 |
| 调度计算 + next_run | `cron/jobs.py` | ~1072-1315 |
| 心跳 | `cron/jobs.py` | ~? |
| 生命周期防护 | `cron/lifecycle_guard.py` | 1-141 |
| 调度器 ABC | `cron/scheduler_provider.py` | 27-73 |
| 内置调度器 | `cron/scheduler_provider.py` | 162-219 |
