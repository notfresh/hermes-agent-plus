# 教学 6：Hermes Gateway — 多平台消息通道

---

## 第一层：直觉 — Gateway 是干嘛的？

想象你在运营一个客服中心。你有 Telegram 用户、Discord 群友、WhatsApp 客户，甚至还有 QQ 群。传统做法：每个平台搞一套独立的机器人，各管各的配置、各存各的对话记录、各写各的代码。

Hermes Gateway 就是把这个"客服中心"统一管起来的中间层。**一个 Agent，对接 N 个聊天平台**。

```
用户发 Telegram ──┐
用户发 Discord  ──┤
用户发 WeChat   ──┤── GatewayRunner ──→ AIAgent ──→ 回复走原路返回
用户发 Signal   ──┤
用户发 QQ 群聊  ──┘
```

所以 Gateway 本质上就是一个**"消息路由器 + 会话管理器 + 流式输出引擎"**。它不负责"思考"，只负责"收发"——把用户的消息喂给 agent，把 agent 的回答送回去。

---

**思考题：** 如果不用 Gateway，每个平台单独部署一个 agent 实例，会有什么坑？

---

## 第二层：动手 — Gateway 的文件地图

gateway 目录下有 **46 个 .py 文件，共 46,543 行**。来看骨架（按重要性排）：

| 文件 | 行数 | 干啥的 |
|------|------|--------|
| `run.py` | 22,984 | Gateway 心脏——GatewayRunner 类、start_gateway 入口、消息处理管道 |
| `slash_commands.py` | 4,915 | 42 个斜杠命令的 handler（/model、/reset、/compress……） |
| `session.py` | 2,815 | 会话管理——怎么跟踪用户、怎么决定是否开始新会话 |
| `config.py` | 2,466 | Gateway 配置加载——平台开关、连接参数 |
| `stream_consumer.py` | 1,966 | 流式输出——agent 边生成边打字的效果 |
| `status.py` | 1,620 | 运行时状态——PID 文件、锁、健康检测 |
| `platforms/base.py` | 5,933 | 平台适配器的 ABC 基类——所有适配器都继承这个 |
| `platforms/` | 27 文件 | 具体各平台的适配器——webhook、signal、qqbot、weixin…… |

run.py 是这里最大的文件（23000 行），但核心逻辑其实很清晰。我们来看看它的类结构：

```python
class GatewayRunner(
    GatewayAuthorizationMixin,     # 用户鉴权
    GatewayKanbanWatchersMixin,    # Kanban 工作队列监听
    GatewaySlashCommandsMixin,     # 斜杠命令处理
):
    """管理所有平台适配器生命周期，在平台与 agent 之间路由消息。"""
    
    def __init__(self, config=None):
        self.config = config or load_gateway_config()
        self.adapters: Dict[Platform, BasePlatformAdapter] = {}
        # ... 还有预填充消息、临时系统提示、推理配置等
    
    async def start(self) -> bool:
        """启动所有已配置的平台适配器"""
    
    async def _handle_message(self, event: MessageEvent):
        """核心消息处理管道"""
```

关键设计模式：**Mixin 分解**。23000 行的类靠多个 Mixin 拆开——AuthorizationMixin 管鉴权，SlashCommandsMixin 管命令，KanbanWatchersMixin 管看板。比起全都是一个类里的方法，这样好维护多了。

---

**动手实验：** 在本地跑跑 `grep -n "class.*Mixin" gateway/run.py | head -20`，看看还有哪些 Mixin。

---

## 第三层：为什么 — 它解决了什么问题？

### 问题 1：怎么让一个 Agent 同时服务 N 个平台？

**答：适配器模式（Adapter Pattern）。** 每个平台有自己的 API（Telegram 用 Bot API 轮询，Discord 用 WebSocket Gateway，微信用公众号回调……），但 Gateway 不需要关心这些细节。

每个适配器都继承 `BasePlatformAdapter`（一个 5933 行的 ABC），实现统一接口：

```python
class BasePlatformAdapter(ABC):
    async def start(self) -> bool:          # 连接平台
    async def stop(self):                    # 断开连接
    async def send(self, chat_id, content):  # 发送消息
    async def send_typing(self, chat_id):    # "正在输入"提示
    async def send_image(self, ...):         # 发图片
    async def send_voice(self, ...):         # 发语音
    # ... plus send_draft, send_clarify, send_document 等 20+ 方法
```

有了这个基类，GatewayRunner 可以**完全不用知道**自己在跟什么平台打交道：

```python
# run.py:9682
def _create_adapter(self, platform, config):
    # 先查插件注册表（平台插件）
    if platform_registry.is_registered(platform.value):
        adapter = platform_registry.create_adapter(platform.value, config)
        return adapter
    
    # 退回内置适配器
    if platform == Platform.SIGNAL:
        return SignalAdapter(config)
    if platform == Platform.WEIXIN:
        return WeixinAdapter(config)
    # ... 还有十几个
```

这也解释了为什么添加一个新平台只需要**写一个适配器类 + 注册到 registry**，核心代码一行都不用改。

### 问题 2：怎么在消息中间处理其他事情（鉴权、斜杠命令、插件拦截）？

**答：管道（Pipeline）模式。** 消息处理是分阶段走的，每个阶段都可以提前终止：

```python
async def _handle_message(self, event):
    # 1. 跨 session 泄漏防护（ContextVars 重置）
    reset_session_vars()
    
    # 2. Plugin hook：插件可以先拦截或改写消息
    result = invoke_hook("pre_gateway_dispatch", event=event)
    if result.action == "skip": return None
    if result.action == "rewrite": event.text = result.text
    
    # 3. 鉴权
    if not is_user_authorized(source):
        if is_dm: offer_pairing_code()
        else: return None  # 群里默默忽略
    
    # 4. 检查斜杠命令
    if event.text.startswith("/model"): handle_model_command()
    if event.text.startswith("/new"):   handle_new_command()
    # ... 42 个命令检查
    
    # 5. 检查是否已有 agent 在跑（busy 策略）
    if session_is_busy():
        if busy_mode == "interrupt": stop_agent()
        elif busy_mode == "queue":   enqueue_message()
        elif busy_mode == "reject":  return "请稍后再试"
    
    # 6. 创建/恢复 session，交给 agent
    source = get_or_create_session(event)
    response = await run_agent(source, event.text)
    
    # 7. 流式返回
    stream = GatewayStreamConsumer(adapter, chat_id)
    stream.start()
```

**每一个阶段都是可插拔的**——想加个新鉴权策略？加一步就行。想加个新斜杠命令？加个 if 分支就行。

---

**思考题：** "添加一个新平台不需要改核心代码"这个设计，你还能在 Hermes 其他模块里看到类似的模式吗？（提示：想想之前学过的 Profider 和 Plugin 系统）

---

## 第四层：细节 — Gateway 的流式输出引擎

Gateway 最有意思的一个设计是**流式打字机效果**。Agent 的 `run_conversation` 是同步的、一次性的——它完整生成完才返回结果。但用户希望看到 AI 一个字一个字地出现在聊天框里。

Hermes 用了 **`GatewayStreamConsumer`** 来解决这个矛盾：

```
agent 同步调用 stream_delta_callback("你好，")
           ↓
GatewayStreamConsumer.on_delta()   ← 线程安全，同步
           ↓
queue.Queue.put(text)
           ↓
asyncio task: 每 N 毫秒从队列取一次
           ↓
adapter.send_typing() + progressive edit
           ↓
用户看到 "|" → "你好|" → "你好，|" → "你好，我|" → ...
```

关键代码：

```python
# stream_consumer.py
class GatewayStreamConsumer:
    """桥接同步 agent 回调到异步平台投递"""
    
    # 队列标记
    _DONE = object()        # 流结束
    _NEW_SEGMENT = object() # tool 调用边界——结束当前消息，开始新消息
    
    def on_delta(self, text: str):
        """Agent 回调——线程安全，放入队列"""
        self._queue.put_nowait(text)
    
    async def run(self):
        """异步任务——从队列取数据，限速编辑"""
        while True:
            item = await self._queue.get()
            if item is _DONE: break
            
            # 积累到 buffer 阈值才推送
            self._buffer += item
            if len(self._buffer) < self._config.buffer_threshold:
                continue
            
            # 编辑已发送消息
            await self._adapter.send(chat_id, self._buffer)
```

这个设计的精妙之处：
- **`queue.Queue`** 是线程安全的——agent 可以在工作线程里同步调用 `on_delta()`，而 asyncio task 安全地消费
- **缓冲 + 限速**——不是每个 token 都推一次，而是积攒到一定量或到达时间间隔才推送，既省 API 调用又不会闪得太快
- **`_NEW_SEGMENT` 标记**——当 agent 在"思考→调用工具→思考→调用工具"之间切换时，结束当前消息重新开始，让用户的聊天记录更清晰

---

**思考题：** 为什么不直接让 agent 支持异步 streaming，而要搞一个队列桥接层？

---

## 第五层：关联 — Gateway 跟 Hermes 其他模块的连接

### 跟 Plugins 的关系
Gateway 的 `pre_gateway_dispatch` hook 用的是 plugins 系统——普通 Hermes 插件可以直接挂钩子来拦截消息处理：
```python
# 插件注册
@ctx.on_hook("pre_gateway_dispatch")
def my_filter(event, gateway, session_store):
    if "敏感词" in event.text:
        return {"action": "rewrite", "text": "***"}
```

### 跟 Cron 的关系
Cron 任务的交付路由（`delivery.py`）通过 Gateway 把定时任务的输出投送到目标平台——同一个发消息的管道。

### 跟 Kanban 的关系
`GatewayKanbanWatchersMixin` 让 Gateway 可以监听 Kanban 看板的任务变化，自动触发任务分配和执行。

### 跟 Profiles 的关系
Gateway 支持**多 profile 复用**——一个 gateway 实例可以用多个 profile 的 bot token 同时连接 Telegram 和 Discord，每个 profile 有独立的配置和 agent 实例。`multiplex_profiles` 配置控制这个行为。

---

**总结：** Gateway 是 Hermes 的"对外窗口"——它用**适配器模式**支持 N 个平台，用**管道模式**处理消息，用**流式消费者**桥接同步 agent 和异步消息投递。它本身不思考，但它保证思考的结果能到达对的人手里。

---

## 📥 静默时段工作小结（00:00 ~ 09:05）

昨晚到今早在静默期间完成了以下探索：

| 产出 | 内容 |
|------|------|
| `teach-3-tool-system.md` （03:07） | 工具系统 3 层架构：registry → toolsets → dispatch |
| `teach-4-plugin-system.md` （06:56） | 插件 4 源发现 + 2 阶加载 + 20+ 生命周期钩子 |
| `teach-5-cron-scheduler.md` （06:57） | 60s tick + 文件锁 + 并行池 + ABC 调度器 |
| `teach-6-gateway.md` （本次） | Gateway 多平台消息通道 |

已探索模块：架构概览 → Agent 核心循环 → 工具系统 → 插件系统 → Cron 调度器 → Gateway ← **当前在此**

---

## 接下来你想做什么？

1. ✅ **继续：deep_dive_skills_memory** — 探索 Hermes 的技能系统和记忆机制
2. ✅ **issue_scanning** — 扫 upstream（NousResearch/hermes-agent）的 issue，找好做的小项目
3. 🔄 **换方向** — 比如你想让我深入某个已经学过的模块，或者看看 hermes-agent-plus 的改动跟 upstream 有什么差异
