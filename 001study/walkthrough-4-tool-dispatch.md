# 走读卡 4：一条 tool_call 的完整旅程——从入口到 registry.dispatch

> 教学读代码序列 · 4 号（tool 系统专项）· 2026-08-13
> 方法论来源：`painless-code-reading` skill + `code-walkthrough-cards` 格式
> 数据来源：实读 conversation_loop → run_agent → tool_executor → model_tools 四条文件 + 本地实验验证
> **本卡作用：把「模型发出 tool_calls 后发生了什么」从头走到尾，最后用 PR #84842 当考题检验理解**

---

## 一、先给结论：一条 tool_call 走 4 层

```
模型输出 tool_calls（assistant message 里的数组）
  ↓ ① 闸门层  conversation_loop.py:4714   —— 名字校验 + 自动修复（valid_tool_names gate）
  ↓ ② 分派层  run_agent.py:6165           —— 按并行安全性分段（单段顺序 / 单段平行 / 多段混合）
  ↓ ③ 执行器  agent/tool_executor.py:1028 —— 逐调用：中断检查→参数解析→tool_search 解包→拦截→执行
  ↓ ④ 调度器  model_tools.py:1025         —— registry.dispatch 真正干活
  ↓ 结果回填  tool_executor.py:1667        —— make_tool_result_message → messages.append
```

一句话：**模型负责「说」，gate 负责「验名」，executor 负责「编排」，registry 负责「干活」。**
读的时候抓住一个主线：**名字**（function_name）从模型的嘴一路传到 registry 的手，中间每层都在对这个名字做校验或改写。

---

## 二、现象入口

模型回合结束后，API 返回的消息里带 `tool_calls` 数组，核心循环进入执行：

```python
# agent/conversation_loop.py:5055
agent._execute_tool_calls(assistant_message, messages, effective_task_id, api_call_count)
```

在此之前（4714-4722）闸门已经验过名——这是**执行前的最后一道"这个工具叫得对吗"检查**（见段 5）。

---

## 三、调用路径图（每步带行号）

```
conversation_loop.py:5055  agent._execute_tool_calls(...)
  │
  ▼
run_agent.py:6165  _execute_tool_calls()          ← 段规划器
  │  _plan_tool_batch_segments（agent/tool_dispatch_helpers.py，按并行安全性分段）
  ├── 1 个调用 / 单段顺序 → run_agent.py:6290 → tool_executor.py:1028 execute_tool_calls_sequential
  ├── 单段平行            → run_agent.py:6285 → tool_executor.py:327  execute_tool_calls_concurrent
  └── 多段混合            → tool_executor.py:1742 execute_tool_calls_segmented

execute_tool_calls_sequential（tool_executor.py:1037 起逐 tool_call 循环）：
  1. 中断检查（1041）         _interrupt_requested → 跳过剩余并回填 cancelled 结果
  2. 参数解析（1062）         _parse_tool_arguments；坏参数 → 直接回 error 结果
  3. tool_search 解包（1084） 名字是 tool_call 桥 → resolve_underlying_call 换回真工具名
  4. 拦截检查（1101-1137）    middleware → 插件 pre_block → guardrail
  5. 特殊工具内联（1247-1490）todo/session_search/memory/clarify/delegate_task/context-engine/memory-provider
  6. 通用路径（1526）         _ra().handle_function_call(...) → model_tools.py:1025
  7. 结果回填（1664-1668）    make_tool_result_message → messages.append

model_tools.py:1025  handle_function_call()      ← registry 调度
  1. coerce_tool_args（1066）      字符串参数按 schema 强转（"42"→42）
  2. Tool Search 桥（1082-1144）   tool_search/tool_describe 内联读目录；tool_call → 解包+scope 门 → 递归
  3. _AGENT_LOOP_TOOLS 拒收（1167）todo 等必须在 agent 循环内处理，registry 不收
  4. 插件 pre_tool_call（1181）    resolve_pre_tool_block
  5. ACP 编辑审批（1219）          写文件类工具的审批闸
  6. registry.dispatch（1265-1278）★ 真身：从注册表找工具实现并调用
  7. post_tool_call hook（1300）+ transform_tool_result 插件缝（1321）
  8. 异常兜底（1349）              任何异常 → {"error": ...} JSON，绝不向上抛
```

**读图要点**：`valid_tool_names`（闸门层的验名名单）出现在 `execute_tool_calls_sequential` 的 else 分支里
（tool_executor.py:1534 传给 handle_function_call 当 `enabled_tools`），它是整个链路的"事实名单"——后面 §五 的 bug 就出在**这张名单的生成时机**。

---

## 四、逐段精读（每段 ≤30 行）

### 段 1：分派层——为什么要有段规划（run_agent.py:6165-6205）

```python
tool_calls = assistant_message.tool_calls
if len(tool_calls) <= 1:
    return self._execute_tool_calls_sequential(...)
from agent.tool_dispatch_helpers import _plan_tool_batch_segments
segments = _plan_tool_batch_segments(tool_calls, execution_cwd=_exec_cwd)
if len(segments) == 1:
    kind = segments[0][0]
    if kind == "parallel":
        return self._execute_tool_calls_concurrent(...)
    return self._execute_tool_calls_sequential(...)
return execute_tool_calls_segmented(self, ..., segments=segments)
```

**为什么**：模型一轮可能发 6 个工具调用。全并行有副作用顺序风险（先 `write_file` 再 `read_file` 不能倒序），
全串行浪费（5 个只读查询没必要排队）。所以按「并行安全」切段：只读/不重叠文件/opt-in 的 MCP 归 parallel 段，
交互/危险/未识别工具是顺序屏障。**混合批次 = 多个段按发出顺序执行，段内并行**。

### 段 2：执行器主循环——每个调用先过 3 道小闸（tool_executor.py:1060-1099）

```python
function_name = tool_call.function.name
function_args, malformed_args_result = _parse_tool_arguments(tool_call.function.arguments)
if malformed_args_result is not None:      # ① 参数解析失败 → 直接回错误结果
    messages.append(make_tool_result_message(function_name, malformed_args_result, tool_call.id))
    continue
# ② tool_search 解包：模型走桥调工具时，把桥名字换回真工具
from tools import tool_search as _ts
if function_name == _ts.TOOL_CALL_NAME:
    _underlying, _underlying_args, _err = _ts.resolve_underlying_call(function_args)
    if not _err and _underlying:
        if _underlying in _tool_search_scoped_names(agent):   # ③ scope 门
            function_name = _underlying
            function_args = _underlying_args
        else:
            _ts_scope_block = f"'{_underlying}' is not available in this session. ..."
```

**关键认知**：`tool_call` 桥在执行层被**解包成真工具**再往下走——所以下游所有 hook（插件 block、guardrail、
post_tool_call）看到的都是真工具名，桥对它们"不可见"（model_tools.py:1129-1130 注释明说这一点）。
这也是为什么 `tool_call(name=...)` 能调起 MCP 工具而直接调用不行——见 §五。

### 段 3：通用路径——把执行权交给 registry（tool_executor.py:1526-1540）

```python
else:
    function_result = _ra().handle_function_call(
        function_name, function_args, effective_task_id,
        tool_call_id=tool_call.id,
        session_id=agent.session_id or "",
        enabled_tools=list(agent.valid_tool_names) if agent.valid_tool_names else None,
        skip_pre_tool_call_hook=True,          # 本层已查过插件 block，避免双触发
        skip_tool_request_middleware=True,     # 同上
        enabled_toolsets=getattr(agent, "enabled_toolsets", None),
        disabled_toolsets=getattr(agent, "disabled_toolsets", None),
    )
```

**两个 skip 是"单一触发契约"**（model_tools.py:1174-1180 注释）：插件 hook 每轮每个工具只能触发一次，
executor 层已查过（段 2 的 1101-1129），所以告诉调度器别再来一遍。`enabled_tools` 把会话工具名单传下去，
`execute_code` 的 sandbox 生成靠它（model_tools.py:1260-1270）。

### 段 4：调度器——registry.dispatch 真身（model_tools.py:1265-1291）

```python
def _dispatch(next_args: Dict[str, Any]) -> Any:
    return registry.dispatch(
        function_name, next_args,
        task_id=task_id, session_id=session_id, user_task=user_task,
    )
result = run_tool_execution_middleware(
    function_name, function_args, _dispatch,
    original_args=_tool_original_args, task_id=task_id or "", ...)
```

**registry 是全局注册表**（本地实验：`registry.get_all_tool_names()` 返回 79 个），
`get_tool_definitions` 只是按 toolset/check_fn 过滤出会话可见子集（本环境 21 个）。
`run_tool_execution_middleware` 是工具执行中件的缝——执行前后还能被 plugin 加工，最后 `transform_tool_result`
（1321）允许插件替换结果字符串。**工具执行的错误面设计**：整个调度包在大 try 里（1349-1352），
任何异常转成 `{"error": ...}` JSON 返回——模型看到的是错误结果，不是崩溃。

### 段 5：验名名单从哪来 + 闸门怎么用（agent_init.py:1221-1223 / conversation_loop.py:4714-4722）

```python
# agent/agent_init.py:1221 —— agent 启动时生成
agent.valid_tool_names = set()
if agent.tools:
    agent.valid_tool_names = {tool["function"]["name"] for tool in agent.tools}

# agent/conversation_loop.py:4714 —— 每轮执行前验名
for tc in assistant_message.tool_calls:
    if tc.function.name not in agent.valid_tool_names:
        repaired = agent._repair_tool_call(tc.function.name)   # 模糊匹配修复
        if repaired:
            tc.function.name = repaired
invalid_tool_calls = [tc.function.name for tc in assistant_message.tool_calls
                      if tc.function.name not in agent.valid_tool_names]
```

**`agent.tools` 是 `get_tool_definitions()` 的返回**（agent_init.py:1214-1218）——注意这函数在
model_tools.py:550-563 的**最后一步**会做 tool_search assembly：把可 defer 的 MCP/plugin 工具替换成
3 个桥（tool_search/tool_describe/tool_call）。**所以 valid_tool_names 是「assembly 之后」的名单**。
这是 §五 bug 的种子。

---

## 五、活教材：PR #84842（MCP 懒加载后工具不在主调度）

**Issue #84772 现象**：progressive disclosure（tool_search）激活时，MCP 工具被藏到 3 个桥后面。
模型直接调用 `mcp__xxx` → 报 "Tool does not exist"（被闸门拦下，因为它不在 post-assembly 名单里）；
但走 `tool_call(name="mcp__xxx")` 却成功（桥路径用 `skip_tool_search_assembly=True` 读**真正的全量目录**，
model_tools.py:1097-1101，再递归 handle_function_call 执行底层工具）。

**根因一句话**：**同一个工具，两条 dispatch 路径读的是两张名单**——
- 直接调用路径：`valid_tool_names`（post-assembly，MCP 被隐藏）→ 闸门拒绝
- 桥路径：`get_tool_definitions(skip_tool_search_assembly=True)`（pre-assembly 全量）→ 成功

**PR #84842 修法**（open，+122 行核心 + 9 个新测试）：
- `model_tools.py` 新增 `has_deferrable_tools()`（便宜的门：用缓存的 `_last_tool_search_assembly` 判断有没有可 defer 工具）
  和 `get_session_tool_names()`（pre-assembly 全量名单，和桥读的是**同一个源**）
- `agent_runtime_helpers.py` 新增 `dispatch_valid_tool_names(agent)` = `valid_tool_names` ∪ pre-assembly catalog，fail-safe
- `conversation_loop.py` 改成每轮算一次 `_dispatch_valid_names`，**9 个 gate 站点**统一换用它
  （repair、invalid_tool_calls、mixed batch、n_valid、error content、JSON skip、invalid batch、strip……）
- 核心工具检查（1702 行）和 codex 逻辑（7343 行）故意不动——**窄修复**

**教学点**：
1. **名单的生成时机**（post-assembly）vs 桥的读取时机（pre-assembly）——同一份配置，两处取数，一处藏一处露。
2. **gate 的扩散**：9 个站点各自 `if name not in agent.valid_tool_names`，修复要 9 处一起换——设计时把"验名"抽成一个函数
   （`_dispatch_valid_names`）就能避免这种多点打补丁。与 teach-18（配置类型契约，两端不一致）同族。
3. **premise 验证**（teach-16 精神）：issue 声称的现象，本地用 `skip_tool_search_assembly` 对比 pre/post 名单就能复现
   ——见实验 2。

---

## 六、动手实验（3 个，已在本机验证可跑）

```bash
cd /root/projects/hermes-agent-plus
.venv/bin/python3
```

**实验 1：registry 全量 vs 会话可见名单**
```python
from model_tools import get_tool_definitions
from tools.registry import registry
defs = get_tool_definitions(quiet_mode=True)
print(len(defs), 'tools visible:', sorted(t['function']['name'] for t in defs)[:8], '...')
print(len(registry.get_all_tool_names()), 'tools in registry')
# 本机输出：21 tools visible（toolset 过滤后） / 79 tools in registry（全量）
```

**实验 2：pre-assembly vs post-assembly（PR #84842 的验证方法）**
```python
pre = get_tool_definitions(quiet_mode=True, skip_tool_search_assembly=True)
post = get_tool_definitions(quiet_mode=True)
pre_names = {t['function']['name'] for t in pre}
post_names = {t['function']['name'] for t in post}
print('hidden by assembly:', sorted(pre_names - post_names))
print('bridge tools:', sorted(post_names - pre_names))
# 本机输出：两者都是 21，差集为空 —— 没有 MCP/plugin 可 defer 工具，assembly 未激活
# 在有 MCP 服务器的环境里，差集就是"被藏起来的工具"，也就是 issue #84772 的现场
```

**实验 3：真实 dispatch 一个只读工具**
```python
import json
r = registry.dispatch('search_files',
    {'pattern': 'def main', 'target': 'files',
     'path': '/root/projects/hermes-agent-plus/hermes_cli', 'limit': 3},
    task_id='card4-exp')
print(r if isinstance(r, str) else json.dumps(r))
# 真实走通了 registry.dispatch 全链路（返回 {"total_count": N, ...}）
```

---

## 七、思考题（3 道）

1. **复述题**：一条 tool_call 要过哪 4 层？`valid_tool_names` 是在哪一层、用什么函数的返回值生成的？
2. **预测题**：`skip_tool_search_assembly=True` 和默认 False 返回的名单差在哪？为什么桥（tool_search）
   必须用 True 的那份？（提示：想想"桥在搜索自己"会怎样）
3. **追问题**：PR #84842 修了 conversation_loop 的 9 个 gate 站点，但特意**不动** model_tools.py:1702 的
   核心工具检查和 7343 的 codex 逻辑——如果统一改成用 `_dispatch_valid_names`，会引入什么风险？
   （提示：思考 pre-assembly 名单里有什么是 post-assembly 故意排除的）

---

## 下一条预告

Tool Search（progressive disclosure）内部：`assemble_tool_defs` 的阈值判定（context 窗口 10%）、
deferrable 名单怎么算、`resolve_underlying_call` 的 scope 门。这条链是本次 PR #84842 的完整背景。
