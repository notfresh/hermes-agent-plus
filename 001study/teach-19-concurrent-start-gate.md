# teach-19：并发工具执行的"开始顺序门"——无超时等待的三宗罪

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/79569（P1，已撞车 PR #79571）
> 姊妹 Issue：https://github.com/NousResearch/hermes-agent/issues/79568（顺序执行路径无超时）
> 关联产出：teach-12（iteration budget）、teach-17（计数器生命周期）、walkthrough-3（ReAct 核心循环）

---

## 现象入口：工具明明只跑 0.5 秒，却报"timed out after 120.0s"？

你让 agent 同时干几件事（读文件 + 搜代码 + 查网页 + 看 skill），它把这批工具**并发**丢进线程池。正常情况下 1 秒内全部返回。但有一天你突然看到：

```
Error executing tool 'read_file': timed out after 120.0s
Error executing tool 'search_files': timed out after 120.0s
```

而 `read_file` 平时只要 0.5 秒。更诡异的是——agent 日志里这些工具**根本就没开始跑**（从头到尾没打印"tool X completed"）。模型收到一堆假失败信息，开始瞎推理、瞎重试。

这个 bug 的根，藏在并发批次里的一个**没有超时上限的等待**上。咱们今天就把这条链拆开看。

---

## 第一层：直觉 —— 考试入场，按号放行

想象一场考试，门口保安按**准考证号**放人：1 号进、2 号进、3 号进……必须按顺序，谁也别想插队。这就是"开始顺序门"（start-ordering gate）。

但注意一个细节：**1 号进场后，是立刻开始做题，还是要等 2 号也进场？**

- 如果保安的逻辑是"1 号必须**做完**，2 号才能开始"——那是串行，慢。
- Hermes 想要的是：**开始**按顺序，但**做**可以同时进行（1 号做题时 2 号、3 号陆续进场开始做）。这样既保住顺序语义，又吃到并发的速度。

于是保安的规则变成：**"轮到谁，谁才能开始；但一旦开始了，各做各的。"**

现在假设 1 号考生进场后**卡住了**（比如他非要先给家里打个电话，电话永远打不通）。保安还在等 1 号"开始"呢，2 号、3 号……全部堵在门口。整个考场死锁——这就是这个 bug 的日常。

💭 **思考题**：为什么 Hermes 要让工具"按顺序开始"，而不是让它们全部立刻开跑、最后**按顺序收结果**就行？想想工具执行有没有副作用（比如写文件、改状态）——"开始顺序"和"完成顺序"哪个更能保证确定性？

---

## 第二层：动手 —— 两个版本的代码对照

好消息：咱们本地 fork 里**没有**这个开始顺序门——本地是"全部开跑 + 完成序回填"。upstream 加了这个门才出的 bug。正好拿来对照，一眼看懂门长什么样。

**本地版（hermes-agent-plus，agent/tool_executor.py:691-693）——无门**：

```python
f = executor.submit(
    propagate_context_to_thread(_run_tool), i, tc, name, args, parsed_calls[i][3]
)
```

worker 一提交就立刻跑，主线程在外面用 5 秒心跳循环等结果（`tool_executor.py:730-734`）：

```python
while True:
    wait_timeout = 5.0
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            ...
```

**upstream 版（NousResearch/hermes-agent，agent/tool_executor.py:806-815）——有门**：

```python
def _begin_in_order(order: int, callback=None) -> None:
    nonlocal next_start_order
    with start_condition:
        start_condition.wait_for(lambda: order == next_start_order)  # ← 无超时
        try:
            if callback is not None:
                callback()        # ← 真正"开始"（dispatch/授权）在这里做
        finally:
            next_start_order += 1
            start_condition.notify_all()
```

门是怎么串起来的（`tool_executor.py:864-869` + `898`）：

```python
def _advance_start(callback=None) -> None:
    ...
    _begin_in_order(start_order, callback)   # worker 开工前先过门

# 提交 worker 时把"过门"挂在 begin_execution 上
begin_execution=_advance_start,
```

每个 worker 线程开工第一件事就是 `_begin_in_order(start_order)`：如果自己的号不是 `next_start_order`，就 `wait_for` 死等；等前面的号把 `next_start_order += 1` 并 `notify_all()`，才放行。

**手走一遍**（模型这轮要跑 3 个工具：read_file=0 号、search_files=1 号、skill_view=2 号）：

1. 三个 worker 同时被提交，各自抢 CPU。
2. 0 号 worker 先到门口：`0 == next_start_order(0)` ✅ 放行，开始执行 read_file。
3. 1 号、2 号 worker 到门口：`1 != 0`、`2 != 0` → 在 `wait_for` 里睡着。
4. 0 号执行完（0.5 秒），finally 里 `next_start_order = 1` + `notify_all()` → 1 号醒，放行。
5. 1 号执行时，0 号的结果已经回填到 `results[0]`。
6. …… 依次类推，**开始**严格按序，**执行**互相重叠。

现在把 0 号换成 skill_view，且它的 dispatch 永远卡住（awaitable 永不 resolve）→ 第 3 步之后再也没有 `notify_all` → 1 号、2 号永久睡在门口。

💭 **思考题**：本地"无门"版会不会有这个 bug？如果不会，upstream 为什么还要加这个门？提示：想想"开始顺序"保证了什么、代价是什么——这俩问题其实是一枚硬币的两面。

---

## 第三层：为什么 —— 门是为什么而设的，超时又为什么缺席

### 为什么要有"开始顺序门"？

工具调用不是纯函数，有**副作用**：写文件、改数据库、调外部 API、推进 checkpoint 状态、触发插件钩子。如果两个工具同时"开始"，它们的副作用提交顺序就不确定——模型看到的中间状态、checkpoint 的快照、dedup 的判断都会变得不可复现。**"开始按序"是"结果按序"更强的一层保证**：它让副作用的发生顺序与模型声明的顺序一致，同时保留执行阶段的并行性。

（本地版的"完成序回填"只保证**模型看到的结果**按序，不保证**副作用发生**按序——两种设计的取舍不同。）

### 为什么 gate 会没有超时？

这才是最有意思的问题。看代码时的直觉是"等待当然要设超时"，但作者没设——**因为 gate 的等待语义是"确定性"的一部分**：理论上每个工具都会在有限时间内"开始"，所以等待是有限等待。问题在于这个假设链条上有两个脆弱环节：

1. **dispatch/授权阶段可能不是有限时间**——`callback()`（`tool_executor.py:811`）里做的是工具分发和授权检查，其中 smart-approval 要调**辅助 LLM**。辅助 LLM 调用被 provider 静默丢弃时（请求发出去了，响应永远不来），这个 callback 就永远不返回。
2. **批次的超时（deadline）管不到 gate**——批次的 120 秒 deadline（`tool_executor.py:994-995`，`HERMES_CONCURRENT_TOOL_TIMEOUT_S`）是主线程在"收结果"时检查的；而 parked 在 `wait_for` 里的 worker 根本不在"执行中"集合里，deadline 到点后它们只是被**放弃**（abandon），人还睡在门口。

于是"有限等待"的假设被打破，而系统没有任何兜底。

💭 **思考题**：如果给 `wait_for` 加一个超时（比如 60 秒），超时后这个 worker 该怎么办？直接开始？还是报错退出？还是继续等但先标记？——想清楚这个问题，你就知道这个 bug 为什么"好报"却"不好修"。

---

## 第四层：细节 —— 三宗罪逐条解剖 + 修复方向

### 罪状一：饥饿（starvation）

gate-holder 卡住 → 所有后面的工具**从未开始**。issue 里贴的现场（SIGUSR2 faulthandler 全线程栈，批次"清理"后 60 秒还在）：

```
File ".../threading.py", line 394 in wait_for
File "/opt/hermes/agent/tool_executor.py", line 750 in _begin_in_order   # ← 卡在这
File "/opt/hermes/agent/tool_executor.py", line 809 in _advance_start
File "/opt/hermes/agent/tool_executor.py", line 409 in _advance_start_order
File "/opt/hermes/agent/tool_executor.py", line 481 in _authorized_dispatch
File "/opt/hermes/hermes_cli/middleware.py", line 215 in run_tool_execution_middleware
```

注意栈里 `_authorized_dispatch`（授权分发）→ middleware → `_begin_in_order`——卡住的正是"开始前的授权"环节，也就是 `callback()` 里的活。

### 罪状二：错误归因（false timeout attribution）

批次 deadline 到点（默认 120 秒），主线程把 `not_done` 的 future 全部标进 `timed_out_indices`（`tool_executor.py:993`、`752`），于是**从没开始跑的** read_file 被报成"timed out after 120.0s"。模型拿到的是假失败信息——它不知道这些工具是被前面的工具饿死的，只会基于假情报重试、换方案，浪费整轮推理。

### 罪状三：泄漏（leaked workers）

批次被放弃时走 `executor.shutdown(wait=False)`（`tool_executor.py:1161`）。为什么敢 `wait=False`？因为用的是 `DaemonThreadPoolExecutor`（`tool_executor.py:1003-1004`，daemon 线程不阻塞解释器退出）。但 daemon 只是"不阻止退出"，**parked 线程本身永远活着**：

- `f.cancel()` 对**已开始运行**的线程无效（cancel 只能拦还没开始的 future）；
- `wait_for` 内部不检查 agent 的 per-thread interrupt 标志（`_set_interrupt`），所以 `/stop` 也救不了它；
- condition 永远不会再被 notify（gate-holder 已经死了）。

一天四个会话，每个泄漏几条线程，慢慢堆积。

### 修复方向（PR #79571 标题可见：bound the concurrent start-order gate wait）

- gate 的 `wait_for` 加**超时边界**（如 60s 或与批次 deadline 联动）；
- 超时后要**区分归因**：`never-started (gate-starved)` vs `started-and-overran`，别让没跑过的工具背"超时"的锅；
- abandon 时对还睡在门上的 worker 做**唤醒/清理**（notify + 置中断标志），别让线程永久 parked。

### 顺带一提的姊妹 bug（#79568）

顺序执行路径 `execute_tool_calls_sequential`（`tool_executor.py:1421`）同样没有 deadline——一个卡住的工具静默拖死整轮。两个 issue 是同一场事故（reporter 拆开报的），同一个修法思路：**给所有"等待"都上边界**。

💭 **思考题**：批次 deadline 明明存在，为什么没拦住这个 bug？——提示：deadline 检查发生在"收结果"的主循环里，而卡住的 worker 不在结果集合里。**"检查超时"和"被检查的对象"不在同一条路径上**，这是这类 bug 的共性。你在 teach-15（compaction 门控）里见过同款结构吗？

---

## 第五层：关联 —— 把它放进你已有的知识地图

1. **与 walkthrough-3（ReAct 核心循环）**：工具调度是核心循环的"手脚"。并发批次是这个循环里唯一"多线程"的地方，其他全是单线程顺序——所以这里的每一条并发防线（daemon pool、deadline、gate）都值得单独记住。

2. **与 teach-12（iteration budget）**：iteration budget 防的是"循环层"的无界消耗（API 调用次数），这个 bug 是"工具层"的无界等待——**两层无界，两种机制，都是"边界"缺失**。Hermes 的防御哲学就是给每个"无限"套上"有限"。

3. **与 teach-17（计数器生命周期）**：teach-17 是"复位点漏了一个"，这里是"等待点没设上限"——都源于**"假设某件事必然发生"**（计数器必然被复位 / 工具必然开始），而现实里假设会破。

4. **与本地 fork 的差异**：本地版没有 gate（完成序回填），upstream 加了 gate（开始序）。如果你在本地 fork 上做实验，可以造一个"gate 卡住"的最小复现：monkey-patch 某个工具的 dispatch 让它 sleep 无限，看本地版会怎样（本地版没有 gate，所以卡的是**执行**而不是**开始**——行为不同，值得亲手对比）。

5. **与 AGENTS.md 铁律**：并发路径上的确定性（顺序语义）是"prompt 缓存神圣"之外的又一条隐性契约——模型的工具调用顺序被当作有意义的输入。

💭 **思考题（开放）**：如果你是修这个 bug 的人，你会把超时设成多少？设太短——慢工具（web_search、terminal）在高峰期会被误杀；设太长——等于没设。**"超时"本身就是设计决策，不是常数**。想想 Hermes 已有的超时（gateway_timeout、child_timeout_seconds）都是怎么选值的，你就能品出这套系统的"安全阀"设计语言。

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/79569
