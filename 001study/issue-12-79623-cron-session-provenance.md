# Issue 12：#79623 Cron 会话缺失 workdir / Git 溯源信息

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/79623
> 关联产出：teach-5（cron 调度器）、walkthrough-3（CLI 核心循环）、issue-11（会话管理）

---

## 📌 一句话总结

**cron 会话和 CLI 会话的 `sessions` 行没有记录 workdir 和 Git 仓库溯源信息**（`cwd`/`git_repo_root`/`git_branch` 全空），导致 `hermes sessions list --workspace <path>` 过滤失效、"resume 恢复到原工作区"的契约断掉。

**状态：🔴 已撞车（08-06T09:0X 更新）** — 推荐后 ~7h，PR #79766（fix(cron): stamp session cwd from configured workdir，thatssoheil，open，+80/-2，2 文件）已 cross-ref。**该 PR 的实现与本报告方案A方向完全一致**（`_launch_cwd_for_session` 加 cron 分支），机制更精确：读 `agent.runtime_cwd._session_cwd_override()` contextvar（scheduler 已把 workdir pin 进 `_SESSION_CWD`），而非本报告设想的 TERMINAL_CWD env bridge，并附 5 个回归测试。本报告保留作教学素材（根因链分析依然有效，且被 upstream 独立验证）。

---

## 现象入口（用户真实场景）

你配置了一个 cron 任务，`workdir: /path/to/git/repo`（Hermes 会在这个仓库目录里执行任务、读取 AGENTS.md）。

任务跑完后，你想用工作区过滤找回这次会话：

```bash
hermes sessions list --source cron --workspace /path/to/git/repo
# → No sessions found 😱
```

但这条会话明明存在——只是不带 `--workspace` 过滤就能看到。再看一眼数据库里的行：

```text
source=cron
cwd=NULL
git_repo_root=NULL
git_branch=NULL
```

而同一个仓库里手动开的 CLI 会话也好不到哪去：

```text
source=cli
cwd=/path/to/git/repo      ← 只有这个有值
git_repo_root=NULL
git_branch=NULL            ← git 字段全空
```

**核心矛盾**：cron 的 workdir 明明生效了（terminal/file 工具都在那个目录里执行），但会话元数据完全没记录它。

---

## 调用路径图（从配置到落库）

```
① cron 任务配置 workdir
   └─ cron/scheduler.py:2990   _job_workdir = job.get("workdir")
        └─ cron/scheduler.py:3019   os.environ["TERMINAL_CWD"] = _job_workdir
             （环境变量 bridge：工具执行时读取，但会话行不读它）

② 调度器启动 agent
   └─ cron/scheduler.py:3340   agent = AIAgent(...)
        └─ cron/scheduler.py:3368   platform="cron"
             （会话 source 从这里来 → "cron"）

③ 首次对话时创建会话行（agent 内部懒创建）
   └─ agent/codex_runtime.py:76 / 156   agent._ensure_db_session()
        └─ run_agent.py:598   _ensure_db_session()
             ├─ run_agent.py:604   source = _session_source_for_agent(self.platform)  → "cron"
             ├─ run_agent.py:621   cwd=_launch_cwd_for_session(source)               → None！
             └─ run_agent.py:613   create_session(...)  ← 只传 cwd，没有 git 字段

④ 落库
   └─ hermes_state.py:2011   create_session(session_id, source, **kwargs)
        └─ hermes_state.py:2013   _insert_session_row(...)  → cwd=NULL, git_*=NULL
```

---

## 逐段精读（根因）

### 片段 1：`_launch_cwd_for_session` — 只认 CLI 的设计

`run_agent.py:68-89`（关键行 80-84）：

```python
def _launch_cwd_for_session(source: str) -> Optional[str]:
    """Working directory to stamp on a new session row, or None.

    Only local CLI sessions get a recorded cwd: the directory the process was
    launched from is meaningful for ``hermes -c`` / ``--resume`` ...
    Gateway/cron/remote-backend sessions have no stable host cwd to restore,
    so they record nothing. ...
    """
    if source != "cli":
        return None                       # ← cron 在这里被挡掉
    backend = (os.environ.get("TERMINAL_ENV") or "local").strip().lower()
    if backend and backend != "local":
        return None
    try:
        return os.getcwd()
    except OSError:
        return None
```

**大白话**：这个函数的设计前提是——只有本地 CLI 会话的"启动目录"有意义（resume 时 chdir 回去）。gateway/cron 在历史上确实没有稳定的工作目录概念，所以直接 `return None`。

**但前提变了**：cron 任务现在支持显式 `workdir` 配置，且调度器已经把它 bridge 到 `TERMINAL_CWD`（cron/scheduler.py:3019）让所有工具执行在正确目录。**工具层跟上了，会话元数据层没跟上**——这就是"intentional design 过期"型 bug：设计当初是对的，新功能（cron workdir）出现后这个假设不再成立。

### 片段 2：`_ensure_db_session` — 创建行时不探测 Git

`run_agent.py:613-623`：

```python
self._session_db.create_session(
    session_id=self.session_id,
    source=source,
    model=self.model,
    model_config=self._session_init_model_config,
    system_prompt=self._cached_system_prompt,
    user_id=None,
    parent_session_id=self._parent_session_id,
    cwd=_launch_cwd_for_session(source),
    profile_name=_profile_for_session,
)
```

**大白话**：创建会话行时只传了 `cwd`，`git_repo_root` / `git_branch` 两个参数压根没出现。数据库层是支持这两个字段的（见片段 3），但 agent 核心路径从不提供值。

### 片段 3：数据库层其实早就支持

`hermes_state.py:2435-2471`（`update_session_cwd`，节选）：

```python
def update_session_cwd(self, session_id, cwd, git_branch=None, git_repo_root=None):
    """... ``git_repo_root`` records the git repo this cwd belongs to — the
    authoritative project key. Resolving it here, at the lowest level, means
    every surface reads the same membership instead of re-probing git in the
    GUI over a partial page. Each field is only written when non-empty so a
    probe failure never clobbers a previously-captured value."""
    branch = (git_branch or "").strip()
    repo_root = (git_repo_root or "").strip()
    sets = ["cwd = ?"]
    ...
    if branch:        sets.append("git_branch = ?");       params.append(branch)
    if repo_root:     sets.append("git_repo_root = ?");    params.append(repo_root)
```

**大白话**：DB 层有完整的 git 溯源写入能力，且做了防御（空值不覆盖已有值——探测失败不会误伤历史数据）。这个函数只被 `tui_gateway/server.py`（前端/桌面路径）调用，**CLI 和 cron 的核心路径从不调用**。所以：

| 路径 | cwd | git_repo_root | git_branch |
|---|---|---|---|
| CLI 会话 | ✅ os.getcwd() | ❌ NULL | ❌ NULL |
| cron 会话 | ❌ NULL | ❌ NULL | ❌ NULL |
| TUI/桌面（前端补写） | ✅ | ✅ | ✅ |

---

## 为什么这样设计（第三层）

**问题**：为什么当初不让所有会话都记 cwd + git 信息？

**答案**（从代码注释还原的设计意图）：
1. **cwd 的语义是"可恢复性"**：CLI 的 cwd 用于 `/resume` 时 `os.chdir()` 回去（`cli.py:6278 _restore_session_cwd`）。gateway 会话没有"宿主目录"可恢复，记了也是假的。
2. **git 探测有成本**：每次建会话都跑 `git rev-parse` 有 IO 开销；探测失败还会产生脏数据。所以设计上把探测下放到前端（TUI 知道用户在工作区时再探测、补写）。
3. **workspace 过滤是后来才有的需求**：`--workspace` 过滤、会话侧栏按仓库分组（tui_gateway/project_tree.py）这些功能建立在 git 字段之上，但建行路径没同步升级。

**有和没有的差别**：没有 = 会话历史无法按仓库检索、resume 无法还原工作区、桌面侧栏分组不完整；有 = 一条 SQL 就能回答"我在这个仓库干过什么"。

---

## 修复方案（两个小改动，可独立验证）

### 方案 A：让 cron 会话记下 workdir（修 cwd=NULL）

`_launch_cwd_for_session`（run_agent.py:68）增加 cron 分支——cron 的 workdir 已经通过 `TERMINAL_CWD` 环境变量传给工具了，直接读它即可：

```python
def _launch_cwd_for_session(source: str) -> Optional[str]:
    if source == "cli":
        backend = (os.environ.get("TERMINAL_ENV") or "local").strip().lower()
        if backend and backend != "local":
            return None
        try:
            return os.getcwd()
        except OSError:
            return None
    # cron：workdir 已由调度器 bridge 到 TERMINAL_CWD（cron/scheduler.py:3019）
    if source == "cron":
        workdir = (os.environ.get("TERMINAL_CWD") or "").strip()
        if workdir and workdir not in (".", "auto", "cwd") and Path(workdir).is_dir():
            return workdir
    return None
```

⚠️ **并发注意**：`TERMINAL_CWD` 是进程级环境变量，cron 调度器用 `_terminal_cwd_lock`（cron/scheduler.py:496）序列化 workdir job。`_ensure_db_session` 在 job 运行期间被调用，锁已被该 job 持有（writer），读到的是自己的 workdir——安全。但 gateway 平台路径也可能设置 `TERMINAL_CWD`（messaging 用 `terminal.cwd` 配置 bridge），需要确认 gateway 会话不受影响（gateway source 不是 "cron"，天然跳过）。

### 方案 B：建行后补写 Git 溯源（修 git_repo_root/git_branch=NULL）

**先说我验证过的一个坑**：`_insert_session_row`（hermes_state.py:1940-1990）的 INSERT 列集合是 `id, source, user_id, session_key, chat_id, chat_type, thread_id, model, model_config, system_prompt, parent_session_id, cwd, profile_name, started_at`——**没有 git 字段**。所以"建行时直接传 git 参数"这条路走不通（除非改 INSERT 语句，动静大）。

**更优路径**：建行后调一次 `update_session_cwd` 补写——这个函数本来就支持 git 字段 + 空值保护（hermes_state.py:2435-2471），且探测工具齐全（`git_probe.repo_root` tui_gateway/git_probe.py:140、`git_probe.branch` git_probe.py:68）：

```python
# run_agent.py _ensure_db_session 里，create_session 之后：
cwd = _launch_cwd_for_session(source)   # 方案A改造后 cron 也有值
if cwd:
    try:
        from tui_gateway import git_probe
        root = git_probe.repo_root(cwd)          # "" = 不在 git 仓库
        if root:
            self._session_db.update_session_cwd(
                self.session_id, cwd,
                git_branch=git_probe.branch(cwd) or "",
                git_repo_root=root,
            )
    except Exception:
        pass  # 探测失败保持 NULL——与 update_session_cwd 的空值不覆盖语义一致
```

**为什么这条路干净**：
- `update_session_cwd` 已有完整测试（tests/test_hermes_state.py:132-190 覆盖 git_branch/git_repo_root 持久化 + 空值不覆盖）
- 探测失败（非 git 目录、git 未装）→ 传空字符串 → 函数内 `if branch:` / `if repo_root:` 自然跳过，不产生脏数据
- 不碰 INSERT 语句，零 schema 风险
- 与 TUI 前端补写走的是同一条函数——三路径最终统一

⚠️ **成本提醒**：每个 CLI/cron 会话建行时多一次 `git rev-parse` 子进程（~几 ms）。tui_gateway 已有 `warm_roots` 并行预热的先例（git_probe.py:182），说明这个成本在项目里是被接受的。可接受。

### 验证方式（本地可跑）

```bash
# 1. 建一个 git 仓库
mkdir -p /tmp/wtest && cd /tmp/wtest && git init -b main

# 2. 起一个 CLI 会话（cwd 记录逻辑）
cd /tmp/wtest && hermes -c "hi" --session-id test-ws-1
hermes sessions list --workspace /tmp/wtest   # 修复后应能找到

# 3. cron 路径
hermes cron add --workdir /tmp/wtest --schedule "1d" --prompt "hi"
hermes cron run <id>
hermes sessions list --source cron --workspace /tmp/wtest   # 修复后应能找到

# 4. 单测（参考现有测试模式）
# tests/test_hermes_state.py:132  test_update_session_cwd_persists_git_branch
# tests/run_agent/test_session_source.py  会话 source 解析
```

---

## 教学价值（为什么值得做）

🎯 **直接命中用户学习重心（会话管理机制）**，四个教学点：

1. **"设计前提过期"型 bug**：`_launch_cwd_for_session` 的注释明明白白写着"cron 没有稳定 cwd"，但 cron workdir 功能上线后这个前提就不成立了。→ 读代码时**要区分"注释说的过去"和"代码现在的行为"**。
2. **环境变量 bridge 的单向性**：`TERMINAL_CWD` 只往"工具执行"方向流，不往"会话元数据"方向流——同一个信息，两条消费路径，一条更新了，一条没跟上。
3. **三层写入路径的不对称**：同一份数据（cwd/git 字段）有三条写入路径（CLI 建行 / cron 建行 / TUI 前端补写），两条没写全。→ 状态写入的"单点归属"设计原则。
4. **与 teach-16（premise verification）呼应**：这个 issue 是"前提确实过期"的正面案例；teach-16 是"前提其实没变"的证伪案例。两个对照着看，就是判断 issue 真伪的完整方法论。

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| 撞车（创建 11h 后仍干净，但随时可能被抢） | 用户确认后尽快开工；本地方案已完整，抢跑成本低 |
| `create_session`/`_insert_session_row` 可能不接受 git 参数 | 开工前先读 hermes_state.py:2011 附近的列集合确认 |
| `TERMINAL_CWD` 被 gateway 平台复用导致误记 | 方案 A 只认 source=="cron"，天然隔离 |
| 方案 B 的探测失败产生脏数据 | 空值不写，与 DB 层既有语义一致 |

---

## 结论

**推荐指数：⭐⭐⭐⭐（干净、修复点明确、教学价值高、本地可验证）**

这是近期少见的"扫到还活着"的核心机制候选。修复本身是两个小改动（~30 行），但覆盖的机制（会话创建、workdir bridge、git 溯源、workspace 过滤）全是 agent 基础原理。**要不要认领这个？** 或者先只看方案不动手？等你表态。

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/79623
