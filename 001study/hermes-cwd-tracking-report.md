# Hermes 当前工作目录（cwd）跟踪机制调查报告

> 调查时间：2026-09-01
> 调查对象：`/usr/local/lib/hermes-agent`（**当前运行的安装副本**，所有行号均指向该副本）
> ⚠️ 行号基线：hermes-agent-plus 研究副本为旧版（`e49d33e6`，无本报告所述双写机制，见 §8 演进对比）——对照时请开安装副本
> 目的：回答「Hermes 如何记住当前工作目录」；为 MinimalAgentV2 的会话管理 / 上下文锚点设计提供依据

---

## 0. 结论摘要（先给答案）

一个 cwd，**三个生命周期各存一份**：

| 层 | 生命周期 | 写时机 | 服务谁 |
|---|---------|--------|--------|
| 内存字典 `_session_cwd`（terminal_tool.py:1247） | 进程内 | **每条 terminal 命令完成后**（三个例外） | 下一条命令从哪跑 |
| SQLite `sessions.cwd` 列（hermes_state.py:5931） | 跨进程 | 会话创建/延续时（写起点目录） | `--resume` 恢复时回到哪 |
| 环境变量 `TERMINAL_CWD` | 进程内 + 子进程 | 入口点（启动/恢复/worktree/cron） | 所有模块和子进程的相对路径坐标 |

关键结论：

1. **不是"每次交互"记录，是"每条命令"记录**——且带三个例外（§7）
2. **广播必须用环境变量而不是 Python 全局变量**：读者里有子进程（shell、code-exec），子进程只继承 env，看不到父进程的全局字典（§5）
3. **状态所有权从"共享"收归"私有"**：早期 cwd 存在共享环境对象上，两个会话并行时 A 的 `cd` 会污染 B——wrong-worktree bug 类的根源（§8）
4. **file 工具的相对路径解析**有完整优先级链：会话记录 > 注册 override > TERMINAL_CWD > 进程 cwd（§6）

---

## 1. 顶层：为什么需要三层

cwd 是"会变、会死、要共享"的易失状态：

- **会变**：agent 随时 `cd` 到别处
- **会死**：进程退出，内存里的值就没了
- **要共享**：terminal 工具、file 工具、code-exec、shell 子进程都要读

三个属性分别逼出一个存储：高频变更 → 内存字典；跨进程存活 → SQLite；跨模块/跨进程共享 → 环境变量。

---

## 2. 运行时主存储：`_session_cwd` 内存字典

**定义**（terminal_tool.py:1247-1248）：

```python
_session_cwd: Dict[str, str] = {}
_session_cwd_lock = threading.Lock()
```

- 进程级模块字典，**以会话键为键**（`task_id`/`session_key`），多会话并行各记各的
- 带 `threading.Lock`——gateway 是多线程，读写互斥

**三个操作函数**：

| 函数 | 位置 | 语义 |
|------|------|------|
| `record_session_cwd(session_key, cwd)` | :1251-1265 | 空/None 键 collapse 到 `"default"`；非字符串/空 cwd 忽略；值变化才写 |
| `get_session_cwd(session_key)` | :1268-1277 | 无回退链——调用方自己决定缺省值（config/TERMINAL_CWD/进程 cwd） |
| `clear_session_cwd(session_key)` | :1280-1283 | 会话拆除时删除 |

**写入链（谁触发）**：命令执行完成后（terminal_tool.py:3640-3641）：

```python
if not workdir and (result or {}).get("cwd_observed"):
    record_session_cwd(session_key, getattr(env, "cwd", None))
```

前置条件（注释 :3622-3639 原话）：
1. env 的 post-command tracking 已把 `env.cwd` 更新为命令结束时的目录（marker 解析，见 §3）
2. **`workdir` 参数不记录**——临时借道，记了会劫持会话的持久 cwd（:3629-3632）
3. **`cwd_observed` 为 False 不记录**——命令被 kill/超时没产出 marker，`env.cwd` 还停在上一条命令的目录（可能是别的会话的），不能错记（:3634-3639）

**读链（谁消费）**：
- `_resolve_command_cwd`（:2786-2816）：`workdir` 参数 > `get_session_cwd()` > `default_cwd`（config/TERMINAL_CWD/进程 cwd）。container 后端还过滤 host 路径（:2805-2815）
- 环境创建（:2911）：`overrides.get("cwd") or get_session_cwd(task_id) or config["cwd"]`

**其他写入口**：`register_task_env_overrides`（:1286-1323）——ACP/TUI/Desktop 会话注册 workspace cwd 时，同步写字典 + 更新 live env.cwd（:1309-1323），"注册的 workspace cwd 就是该会话的工作目录，直到 `cd` 改变它"。

---

## 3. env 层：共享环境对象的 `cwd` 属性（历史遗留）

local/remote 后端环境对象持有 `self.cwd`，命令后同步。**这是旧机制的残留**，注释（:1236-1246）明说它是 wrong-worktree bug 类的根源：env 跨会话复用，env 上的 cwd 是"全局可变状态，被多个会话分时共享"。

**marker 机制**（tools/environments/base.py:1410-1438）：远程后端（Docker/SSH/Modal/Daytona/Singularity）用输出 marker 解析 cwd：

- wrapper 在命令返回后打印 `printf '\n__MARKER__%s__MARKER__\n'`（:1441-1442）
- `_extract_cwd_from_output` 找 `__HERMES_CWD_{session}__` marker（:1424），解析出路径 → `self.cwd = cwd_path` + `result["cwd_observed"] = True`（:1435-1438）
- **kill/超时命令无 marker** → `cwd_observed` 不设 → 上层不记录（§2 的第三例外正是靠它门控）
- local 后端 override `_update_cwd`（:1406-1408，"local file-based read"）
- local.py:2045 某路径会 `result.pop("cwd_observed", None)`（不支持的后端清掉标志）

**演进方向**（:1242-1246 注释）：当前是 "Step 1 dual-write only"——写点同时写字典；后续步骤把 file_tools 和 `_resolve_command_cwd` 的读取也翻转到字典，删掉 env 侧的跟踪和所有权守卫。

---

## 4. 持久化：SQLite `sessions.cwd` 列

**写**：会话创建/延续时（hermes_state.py:5931 `cwd: str = None` 参数；:6018 upsert `COALESCE`；:5956-5978 注释：branch continuation 也带本行 cwd/git_repo_root）。

**语义 = "这个会话从哪来"**：中途 `cd` 一万次不落库。恢复时回到**起点目录**，不是上次 cd 的位置。

**读**（恢复流程 `_restore_session_cwd`，cli.py:8604-8655）：

```
session_meta["cwd"] ─→ expanduser ─→ 与当前 realpath 比较（已在该目录则跳过）
    ├─ 目录不存在 → 降级警告（"Session's working directory is gone"），不崩溃
    └─ os.chdir(recorded)  +  os.environ["TERMINAL_CWD"] = recorded
        └─ 打印 "↻ Working directory: ..."
```

三个恢复入口：`cli_agent_setup_mixin.py:458`（启动 --resume/-c）、`:726`（其他 resume 路径）、`cli_commands_mixin.py:1200`（对话内 /resume）。

**其他读**：hermes_state.py:248-260（取某会话 cwd）；:282-310 `_cwd_prefix_clause`（按 cwd 前缀过滤会话历史，`git_repo_root` 为空时回退 cwd 前缀匹配）。

---

## 5. 广播：`TERMINAL_CWD` 环境变量

**为什么必须是环境变量**：读者里有**子进程**（shell wrapper、code-exec sandbox）。子进程 fork 时自动拷贝父进程全部 env——这是 Python 全局字典做不到的通道。

**谁写（入口点级，低频）**：

| 入口 | 位置 | 值 |
|------|------|-----|
| 会话恢复 | cli.py:8649 | 从 SQLite 读出的起点 cwd |
| worktree 模式（-w） | cli_commands_mixin.py:1368 | worktree 路径 |
| gateway 启动 | gateway/run.py:2634 | 解析后的 cwd |
| cron job（有 workdir） | cron/scheduler.py:5879 | job workdir；结束后 :6762 还原 `_prior_terminal_cwd` |
| TUI 服务 | tui_gateway/server.py:14420 | 会话 cwd |

**配置桥接**：`terminal.cwd`（config_defaults.py:384，默认 `"."` = 启动目录）→ 启动时 bridge 成 TERMINAL_CWD（config.py:613/647-653 force-export；config_defaults.py:5063-5064：MESSAGING_CWD 已移除，gateway 从 terminal.cwd 桥接）。

**谁读**：
- file 工具相对路径锚点（file_tools.py:251-259 `_configured_terminal_cwd`，只认绝对 + sentinel-free）
- code-exec、shell 包装器
- `_safe_getcwd` 兜底（terminal_tool.py:1619-1635）：`os.getcwd()` 失败（目录被删 / macOS TCC 权限）→ TERMINAL_CWD → home
- bang_shell（cli 的 `!` 命令，bang_shell.py:86-93）读 `get_session_cwd`

**防御**：
- **sentinel 值拒绝**（file_tools.py:163-171）：`{"", ".", "./", "auto", "cwd"}`——stale config 留下的字面 `"."` 不当作相对锚点，否则会把编辑路由到 agent 进程 cwd（错误 checkout）
- **container 后端过滤**（terminal_tool.py:1809-1833）：docker 显式挂载时 host 路径 remap 到 `/workspace`（:1818-1826）；其他 container 后端遇到 host/相对路径直接丢弃用默认（:1827-1833）
- **遗留清理**（:2911-2915）：新会话环境创建时，"must not inherit the process-global TERMINAL_CWD mount left behind by a previous session"——per-session 隔离下 `host_cwd` 走 `_resolve_task_host_cwd` 单点解析

---

## 6. file 工具的路径解析链

相对路径解析的**绝对基目录** `_resolve_base_dir`（file_tools.py:315-370），优先级：

1. **会话 live cwd 记录**（`get_session_cwd(task_id)`，:342 → :281-312 `_authoritative_workspace_root`）——每命令更新，权威
2. **注册的 task/session cwd override**（TUI/Desktop/ACP 先注册，:309-311）
3. **sentinel-free 绝对 TERMINAL_CWD**（worktree 路径，:312）
4. **进程 cwd**（最后兜底，:348）

不变量：**返回的 base 永远是绝对路径**（:332-340）——相对/sentinel 的 TERMINAL_CWD 直接拒绝，而不是锚到进程 cwd，这是防 worktree-cwd 分歧的核心。

派生保护：`_path_resolution_warning`（:410+）——相对路径解析到 workspace root 之外时返回警告，第一次写就提示。

---

## 7. 写入时机：不是"每次交互"，是"每条命令"

| 层 | 写频率 | 服务场景 |
|---|--------|---------|
| 内存字典 + env.cwd | **每命令**（三个例外：workdir / 无 cwd_observed / 非 terminal） | 下一条命令从哪跑 |
| SQLite cwd 列 | 每会话一次（创建/延续） | 跨进程恢复 |
| TERMINAL_CWD | 每入口点一次 | 模块/子进程坐标 |

"交互"（用户说一句话）和"命令"（agent 执行的一条 shell）是两个粒度：一轮交互里可能跑 N 条命令，每条成功完成的命令都触发一次字典更新。

---

## 8. 设计取舍与演进

**三个取舍**：

1. **每命令写 DB 太贵**。即时需求只有"下一条命令从哪跑"，内存字典就够；SQLite 只服务低频的跨进程恢复
2. **广播只需入口点级更新**。file 工具读的是"当前坐标"不是流水账，入口点对整齐即可
3. **状态所有权从共享收归私有**。共享 env.cwd 是 wrong-worktree bug 类根源（:1236-1246），per-session 字典让一个会话的 `cd` 永远进不了另一个会话的解析

**演进实证**（新旧版对比）：

| | hermes-agent-plus 副本（旧版 e49d33e6） | 安装副本（当前运行版） |
|---|-----------------------------------------|------------------------|
| `_session_cwd` 字典 | 存在（:1086） | 存在（:1247） |
| `record_session_cwd` | **只有定义，无调用点**（未接线） | :3640 命令后 dual-write 调用 |
| `cwd_observed` 门控 | 无 | 有（base.py:1416-1438） |
| `_restore_session_cwd` | 无 | cli.py:8604 |

→ 机制演进顺序：TERMINAL_CWD 环境变量（共享广播）→ env.cwd（共享对象）→ **per-session 字典双写（收权）**。当前代码处于过渡期：写入已双写，读取还走旧链（env.cwd ladder），注释明说后续翻转。

---

## 9. 测试覆盖（对照验证用）

- `tests/tools/test_session_cwd_store.py` — 字典存取/键 collapse
- `tests/tools/test_interrupted_command_cwd.py` — **cwd_observed 门控**：中断命令不记录（防止串味的关键测试）
- `tests/tools/test_resolve_path.py` — 相对路径优先 recorded session cwd
- `tests/tools/test_file_tools_tilde_profile.py` — `_session_cwd` 重置
- `tests/cli/test_cwd_env_respect.py`、`tests/cli/test_worktree.py`、`tests/hermes_cli/test_worktree_command.py` — TERMINAL_CWD/工作区
- `tests/cron/test_cron_workdir.py:300` — cron 结束还原 TERMINAL_CWD
- `tests/tools/test_terminal_env_bridge.py:96` — `TERMINAL_CWD == "~"`（ssh 远程 tilde 特例）
- `tests/tui_gateway/test_session_cwd_follow.py` — 会话 cwd 跟随 worktree
- `tests/test_hermes_state.py:346` — `session["cwd"] == "/work/repo"`

---

## 10. 对 V2 的启示（简短）

V2 的 session_manager 已有同款分层直觉：会话"存在" = 文件（档案）+ 索引（活体），延迟持久化（第一条真实消息才落盘）。cwd 机制是同一模式的完整工业版，可抄的点：

1. **易变状态三层化**：活体（内存，命令级）/ 档案（持久化，会话级）/ 广播（共享通道，入口级）——判断问三问：谁会读？活多久？变多快？
2. **门控写入**：只有"确实观察到"的状态才落记录（cwd_observed），防止把中间态/他人态写进来
3. **所有权收归私有**：任何"会话该记住"的状态不要放在共享对象上，按会话键存
4. **恢复语义明确**：持久化的是"起点"不是"最新"，恢复行为可预期
