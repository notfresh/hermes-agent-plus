# 走读卡 3：CLI 主核心 + 核心 Loop — 从你敲回车到 Hermes 回答，发生了什么？

> 教学读代码序列 · 第 3 份 · 2026-08-05
> 配套：走读卡 1（skill 加载）→ 2（frontmatter 解析）→ 本卡进入 agent 主战场
> 代码版本：hermes-agent-plus（本地 fork）
> **本卡所有代码都标注 文件:行号，请打开对应源码对照着读**

---

## 一、现象入口

你在终端里敲 `python cli.py`，看到欢迎横幅，输入"帮我看看这个文件"，回车——几秒后 Hermes 开始流式输出回答，中途可能还调了工具。

问题：从**回车**到**回答结束**，代码里到底经过了哪些环节？CLI 和"agent 核心循环"是同一个东西吗？

答案先给你：**不是**。CLI 是"外壳"（画界面、读输入、渲染输出），核心循环是"引擎"（想、调工具、再想）。本卡把两个都讲清楚。

## 二、调用路径图（带精确位置）

```
python cli.py
   │
   ▼
cli.py:15384  main()                          ← 入口：解析参数、建 HermesCLI
   │
   ├── 单查询模式 (-q)  → cli.py:15793  cli.agent.run_conversation(...)
   │
   └── 交互模式 (无 -q)  → cli.py:12749  HermesCLI.run()   ← 主循环
                            │
                            │  prompt_toolkit 事件循环：Enter 键 → cli.py:12991 handle_enter()
                            │  → 消息进 _pending_input 队列（:12902）
                            ▼
                         后台线程 process_loop 取消息 → cli.py:11590  chat(message)
                            │
                            │ ① _ensure_runtime_credentials() 刷新凭证      :11620
                            │ ② _resolve_turn_agent_config() 决定模型路由  :11623
                            │ ③ _init_agent() 建/复用 agent                 :11630
                            │ ④ 图片路由 / @上下文 / 清洗消息               :11646-11725
                            │ ⑤ _stage_user_message() 把消息放进历史        :11739
                            ▼
                         cli.py:11900  self.agent.run_conversation(...)
                            │
                            ▼
              agent/conversation_loop.py:588  run_conversation()   ← 核心引擎
                            │
                            │ ① build_turn_context() 每轮一次性准备        :641
                            │ ② while 主循环                               :715
                            │     ├─ 中断检查？                           :720
                            │     ├─ 迭代预算扣减？                       :734
                            │     ├─ 组装 messages → API 调用             :827+
                            │     ├─ 模型返回 tool_calls？
                            │     │     ├─ 是 → _execute_tool_calls()     :5055
                            │     │     │       工具结果塞回 messages
                            │     │     │       → continue 下一轮          :5151
                            │     │     └─ 否 → final_response = 回答内容  :5155
                            │     └─ 循环退出：max_iterations / 预算 / 中断
                            ▼
                        返回 result dict → chat() 渲染 → 回到输入框等你下一句
```

## 三、逐段精读（每段标注位置，请对照源码）

### 段 1：入口 main() — 参数怎么变成 CLI 实例（cli.py:15384-15543）

```python
def main(query=None, q=None, image=None, toolsets=None, skills=None, ...):
    # 单查询模式：query 或 q 任一给了就执行一次然后退出
    query = query or q                       # :15494  别名合并

    # 工具集解析：没显式指定时，在代码工作区自动折叠成 coding 工具集
    toolsets_list = None
    if toolsets:
        # ... 逗号分隔 / 元组 → 列表                 :15499-15509
    else:
        from agent.coding_context import coding_selection
        _coding = coding_selection(platform="cli", config=CLI_CONFIG)  # :15517
        toolsets_list = _coding or sorted(_get_platform_tools(...))    # :15521-15525

    cli = HermesCLI(model=model, toolsets=toolsets_list, ...)          # :15530
```

大白话：
- **`query = query or q`（:15494）**：`--query` 和 `-q` 是同一个东西的两个名字，这里合并。给了就走单查询，没给就走交互。
- **工具集默认值不是写死的（:15511-15525）**：站在代码目录里启动时，`coding_selection()` 自动给你 coding 工具集——"我在写代码"这个上下文是探测出来的，不是用户配置的。
- **HermesCLI 一个实例管整个会话（:15530）**：会话状态（历史、session_id、agent 实例）都挂在它上面。

### 段 2：交互主循环入口 run()（cli.py:12749-12908）

```python
def run(self):
    if not self._claim_active_session("cli"):   # :12751  会话锁，防止两个 CLI 抢
        return
    self.show_banner()                          # :12772
    ...
    # 三个关键状态容器（:12900-12908）
    self._agent_running = False
    self._pending_input = queue.Queue()         # ← 空闲时输入走这个队列
    self._interrupt_queue = queue.Queue()       # ← agent 跑着时输入走这个队列
    self._should_exit = False
```

大白话，理解这个文件的关键：
- **两个队列的设计（:12902-12903）**：agent 空闲时你敲的字进 `_pending_input`；agent 正在干活时你敲的字进 `_interrupt_queue`——这就是"中途打断"的实现基础（后面 chat() 会轮询它）。
- **`_claim_active_session`（:12751）**：一个 session 同时只允许一个进程在用，防止开两个终端把会话状态写乱。

### 段 3：Enter 键怎么被分发 — handle_enter()（cli.py:12991-13038）

```python
def handle_enter(event):
    # 按当前 UI 状态路由 Enter：密码框/确认框/clarify/模型选择器...
    if self._sudo_state:                        # :13005
        self._sudo_state["response_queue"].put(text)
        ...
    if self._approval_state:                    # :13021
        self._handle_approval_selection()
        ...
    # 默认路径：agent 空闲 → 普通输入队列
    # agent 运行中 → 中断队列（命令 / 开头的除外）
```

大白话：**同一个 Enter 键，在不同 UI 状态下干不同的事**。这解释了为什么密码提示、危险命令确认、clarify 选择题能共用同一个输入框——全靠 `_xxx_state` 标记路由。

### 段 4：一轮对话 chat() — 调用核心循环前做了什么（cli.py:11590-11935）

```python
def chat(self, message, images=None):
    self._last_turn_interrupted = False          # :11617  重置中断标记
    if not self._ensure_runtime_credentials():   # :11620  刷新 API 凭证
        return None
    turn_route = self._resolve_turn_agent_config(message)  # :11623  模型路由
    if turn_route["signature"] != self._active_agent_route_signature:
        self.agent = None                        # :11624-11625  模型变了→重建 agent
    if not self._init_agent(...):                # :11630
        return None
    # 图片路由：模型支持视觉→原生图片；不支持→先 vision_analyze 描述
    # @上下文展开：@file:main.py 之类            :11698-11718
    # 清洗消息：孤立代理字符会炸 JSON             :11723-11725
    self._stage_user_message()                   # :11739  用户消息入历史
    ...
    def run_agent():
        result = self.agent.run_conversation(    # :11900  ← 核心循环在这
            user_message=agent_message,
            conversation_history=self.conversation_history[:-1],
            ...
        )
    ...
```

大白话：
- **`_ensure_runtime_credentials`（:11620）**：每次对话前检查 API key，支持自动轮换——"key 过期了"这种错误不应该让用户手动处理。
- **`_resolve_turn_agent_config`（:11623）**：每条消息可能路由到不同模型（比如 /model 切过一次）。签名变了就重建 agent 实例（:11624）。
- **`conversation_history[:-1]`（:11902）**：消息已经在 :11739 塞进历史了，传给核心循环时**去掉最后一条**——避免重复。这种"先暂存、再传、再对齐"的模式在 Hermes 里到处都是，是防重复的老手笔。

### 段 5：核心循环骨架 — run_conversation()（agent/conversation_loop.py:588-741）

```python
def run_conversation(agent, user_message, system_message=None,
                     conversation_history=None, task_id=None, ...):
    # ① 每轮一次性准备（prologue）：清洗、系统提示词、压缩预检...
    _ctx = build_turn_context(agent, user_message, ...)   # :641
    messages = _ctx.messages                               # :663
    ...
    # ② 计数器（纯局部变量，循环里读）
    api_call_count = 0
    final_response = None
    interrupted = False

    # ③ 主循环：两个退出条件同时生效
    while (api_call_count < agent.max_iterations
           and agent.iteration_budget.remaining > 0) or agent._budget_grace_call:
        # 中断检查：用户在 agent 干活时打字了？
        if agent._interrupt_requested:                     # :720
            interrupted = True
            break
        api_call_count += 1                                # :727
        # 迭代预算：每次调用扣一分，扣完就停（除非 grace call）
        if agent._budget_grace_call:
            agent._budget_grace_call = False
        elif not agent.iteration_budget.consume():         # :736
            break                                          # 预算耗尽
        ...
        # ④ 组装 messages → 调 API（在 :827 之后的巨大分支里）
        # ⑤ 看模型返回什么（在 :5055 / :5155）
```

大白话，这是整个 agent 的心脏：
- **循环条件有两个闸（:715）**：`max_iterations`（回合硬上限）和 `iteration_budget.consume()`（预算制，扣一分少一分）。两个都看——这就是走读卡 1 提过的"预算机制"落地。
- **`_budget_grace_call`（:734）**：预算耗尽了还给模型一次"最后机会"，防止"就差一步"时被硬生生掐断。用完即焚。
- **中断检查在循环顶部（:720）**：所以"用户打字打断"最快也要等当前 API 调用返回才能生效——不是即时的。

### 段 6：循环的两种出口 — 有工具调用 vs 最终回答（conversation_loop.py:5055 / 5153-5155）

```python
# 模型返回了 tool_calls → 执行工具，把结果塞回消息，继续循环
agent._execute_tool_calls(assistant_message, messages,
                          effective_task_id, api_call_count)   # :5055
...
# 压缩上下文（如果快超长）后继续下一轮
messages, active_system_prompt = agent._compress_context(...)  # :5138
continue                                                        # :5151

# ── 模型没返回 tool_calls → 这就是最终回答 ──
else:
    final_response = assistant_message.content or ""            # :5155
```

大白话，核心循环的本质一句话：
**"把 LLM 的输出检查一遍——如果它说'我要调工具'，就去执行、把结果喂回去、再问一次；如果它直接给答案，就收工。"** 这就是 ReAct 循环的代码形态：Thought（模型想）→ Action（tool_calls）→ Observation（工具结果塞回 messages）→ 再 Thought……直到没有 Action。

## 四、动手实验（3 分钟，本地可做）

```bash
cd /root/projects/hermes-agent-plus

# 1. 看核心循环的两个退出条件到底是多少（默认配置）
python3 -c "
import ast
# 直接读源码确认默认值
src = open('cli.py').read()
print('max_iterations 默认值注释: 见 cli.py:15422 → default: 60')
print()
print('iteration_budget: 在 agent/iteration_budget.py 定义')
"

# 2. 追踪一次真实的 run_conversation 调用（看 chat() 怎么把消息传进去）
grep -n "run_conversation" cli.py | head -5
echo "---"
grep -n "def run_conversation" agent/conversation_loop.py

# 3. 看一个真实的 tool_calls 在消息里的样子（用你今天的会话日志）
ls -t /root/.hermes/sessions/ 2>/dev/null | head -3
```

## 五、思考题（3 道，答完我批）

1. **复述题**：交互模式下，从你敲回车到 agent 开始思考，消息经过了哪几个队列/函数？（提示：handle_enter → _pending_input → chat → run_conversation）
2. **预测题**：如果我把 `while (api_call_count < agent.max_iterations and agent.iteration_budget.remaining > 0)` 改成只看 `api_call_count < agent.max_iterations`（去掉预算），会有什么行为差异？什么时候 budget 会比 max_iterations 先到？（提示：想想预算可能被别的机制消耗——查 agent/iteration_budget.py）
3. **追问题**：`chat()` 里 `_stage_user_message()` 把消息加进 `self.conversation_history`，然后调用核心循环时传的是 `conversation_history[:-1]`——为什么传"去掉最后一条"的版本？如果传完整列表会出什么问题？（提示：想想核心循环会不会把 user_message 再追加一次）

---

下一条预告：tool/toolset 系统的加载与注册——`_execute_tool_calls`（:5055）进去之后，工具是怎么被找到、鉴权、执行的。读完这张卡、做完实验，回我结果或卡点，明天出第 4 份。
