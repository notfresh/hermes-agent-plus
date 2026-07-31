# Hermes 工具系统揭秘：从自发现到安全执行

> tick=3, phase=deep_dive_tools
> 教学层级：5层渐进式

---

## 第一层：直觉 — 这是什么东西？

想象一下你开了一家餐厅：

- **工具** = 厨房里的食材和厨具（刀、砧板、炉子、盐、胡椒）
- **工具集（toolset）** = 今天菜单上的一组菜品（"法式套餐" = 前菜+主菜+甜点）
- **注册表（Registry）** = 储藏室管理员，知道每样东西在哪、有没有过期
- **model_tools.py** = 主厨，根据客人的要求决定今天做什么菜
- **check_fn** = 食材新鲜度检查（"这个番茄能用吗？"）

那 Hermes 的工具体系本质上就是：**"让LLM能看到并调用正确的工具，同时保证安全性和灵活性"**。

举个例子：你在 CLI 里问 Hermes "帮我搜一下这个文件"，这时候：

1. Hermes 先查"今天用什么模具（toolset）" → CLI 模式用的是 `hermes-cli` 工具集
2. 查工具集里的 `search_files` 工具 schemas → 告诉模型："你可以调 search_files"
3. 模型说"好，调用 search_files 吧" → 参数传递 + 安全检查 → 实际执行
4. 结果返给模型 → 模型给你答复

整个过程你感觉不到，但实际上每一步都有精密的编排。

> 💭 **思考一下**：如果你是设计师，你会怎么设计一个"让AI模型安全地调用各种工具"的系统？

---

## 第二层：动手 — 具体是怎么做的？

我们来亲手走一遍工具加载和调用的全过程。

### 2.1 工具自动发现

Hermes 的工具都在 `tools/` 目录下。每个 `.py` 文件只要在顶层调用了 `registry.register()`，就会被自动发现。不用手动维护导入列表。

```python
# tools/registry.py - 自发现核心逻辑

def discover_builtin_tools(tools_dir=None):
    """扫描 tools/ 目录，自动导入每个有 register() 调用的模块"""
    tools_path = tools_dir or Path(__file__).parent
    
    # 先检查每个文件是否真的调用了 registry.register()
    for path in sorted(tools_path.glob("*.py")):
        if path.name in {"__init__.py", "registry.py", "mcp_tool.py"}:
            continue  # 跳过这些特殊文件
        if _module_registers_tools(path):      # ← 用 AST 静态分析
            importlib.import_module(f"tools.{path.stem}")
            
def _module_registers_tools(module_path):
    """检查文件里有没有顶层 registry.register() 调用"""
    source = module_path.read_text()
    if "registry" not in source or "register" not in source:
        return False  # 快速过滤：不可能包含注册调用
    
    tree = ast.parse(source)
    return any(_is_registry_register_call(stmt) for stmt in tree.body)
```

关键技巧：它用 `ast.parse` 做**静态分析**，只检查**模块顶层**的 `registry.register()` 调用。函数内部的注册调用会被忽略——这样 helper 模块不会误伤。

### 2.2 工具注册表（Registry）

当你写一个新的工具文件时（比如 `tools/your_tool.py`），你只需要这样注册：

```python
# tools/your_tool.py
import json
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("YOUR_API_KEY"))

def your_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"result": f"hello {param}"})

registry.register(
    name="your_tool",
    toolset="custom",        # 属于哪个工具集
    schema={                  # OpenAI-format tool schema
        "name": "your_tool", 
        "description": "...", 
        "parameters": {...}
    },
    handler=lambda args, **kw: your_tool(param=args.get("param", "")),
    check_fn=check_requirements,   # 可选：只有满足条件才暴露
    requires_env=["YOUR_API_KEY"],
)
```

### 2.3 工具集（Toolsets）的分层结构

`toolsets.py` 里定义了**核心工具**和**扩展工具集**：

```python
# toolsets.py - 核心工具（所有平台都有的）
_HERMES_CORE_TOOLS = [
    "web_search", "web_extract",
    "terminal", "process",
    "read_file", "write_file", "patch", "search_files",
    "vision_analyze", "image_generate",
    "skills_list", "skill_view", "skill_manage",
    "browser_navigate", "browser_snapshot", "browser_click", ...
    "text_to_speech",
    "todo", "memory",
    "session_search",
    "clarify",
    "execute_code", "delegate_task",
    "cronjob",
    "ha_list_entities", ...
    "computer_use",
]

# 各种平台专用工具集
TOOLSETS = {
    "web": {"tools": ["web_search", "web_extract"]},
    "terminal": {"tools": ["terminal", "process"]},
    "file": {"tools": ["read_file", "write_file", "patch", "search_files"]},
    "messaging": {"includes": ["hermes-cli"],  # 继承 CLI 工具再加消息通道
                   "tools": ["send_message", ...]},
    "kanban": {"tools": ["kanban_show", "kanban_complete", ...]},
    ...
}
```

### 2.4 分发执行

当模型说"我要调 `search_files`"，`handle_function_call` 负责路由：

```python
def handle_function_call(function_name, function_args, ...):
    # 1. 参数类型强制转换（"42" → 42）
    function_args = coerce_tool_args(function_name, function_args)
    
    # 2. 安全检查中间件
    from hermes_cli.middleware import run_tool_execution_middleware
    result = run_tool_execution_middleware(
        function_name, function_args, lambda args: registry.dispatch(
            function_name, args, task_id=task_id, ...
        )
    )
    
    # 3. 最后才叫 registry.dispatch() 执行真正的处理函数
    return result
```

> 💭 **动手思考题**：如果你在 tools/ 下新建一个 `my_cool.py`，写了 `registry.register()`，Hermes 会自动发现它。但模型看不到它——为什么？需要再做什么？

---

## 第三层：为什么 — 它解决了什么问题？

### 3.1 "窄腰"设计哲学

Hermes 的核心设计原则之一是 **Core as Narrow Waist**（核心是窄的瓶颈）。什么意思？

> **没有窄腰之前**：每个新功能都加一个核心工具 → 每个 API 调用都要传输这些工具 schemas → 模型收到的提示越来越胖 → 越来越贵、越来越慢
> 
> **有了窄腰之后**：核心工具只有几十个，大部分能力通过 CLI 命令 + skill 或 plugin 实现，不增加模型 API 调用的 payload

看看 toolsets.py 里 80 多行核心工具，再看看 TOOLSETS 字典里几十个扩展工具集——只有核心工具是每个请求都必须发送的。`kanban`、`homeassistant`、`feishu_doc` 这些扩展工具集**只有当你开启了对应功能**时才会出现在 schema 里。

### 3.2 缓存（Cache）无处不在

工具系统有三个层次的缓存：

| 缓存层 | 位置 | 目的 |
|--------|------|------|
| check_fn TTL 缓存 (~30s) | registry.py | Docker daemon 探针、Playwright 探针这些外部检查不重复跑 |
| check_fn 瞬态失败容忍 (~60s) | registry.py | Docker 偶尔超时不算"下线" |
| get_tool_definitions 缓存 (最多8个) | model_tools.py | 频繁的转调用 (gateway每turn都问) 不重建 schemas |

为什么这么重视缓存？因为：
- 核心工具 schemas 可能在每次 API 调用时都发送
- Gateway 模式下每一条消息都要重新获取工具定义
- 缓存失效由 `registry._generation` 计数器自动处理——注册/注销工具时 +1

### 3.3 安全检查的分层设计

```python
# 第一层：check_fn — 环境前置检查
check_fn=lambda: bool(os.getenv("DOCKER_HOST"))  # Docker 没装就不暴露 terminal

# 第二层：预执行中间件 — tool_request_middleware
# 可以修改参数、记录调用、拒绝请求

# 第三层：插件钩子 — pre_tool_call / post_tool_call
# 插件可以 hook 任何工具调用（比如审计、速率限制）

# 第四层：文件安全 — 防止写敏感文件
WRITE_DENIED_PATHS = ["/etc/passwd", "/root/.ssh/", ...]
```

> 💭 **思考题**：如果你是一家公司的安全官，你会希望 Hermes 的模型能直接 `write_file` 到 `/etc/` 目录下吗？这个分层设计能不能让你灵活控制权限？

---

## 第四层：细节 — 源码里怎么实现的？

### 4.1 ToolRegistry 的注册核心

让我们看看 `registry.py` 里 `register()` 方法的完整逻辑：

```python
def register(self, name, toolset, schema, handler, check_fn=None,
             requires_env=None, is_async=False, description="", emoji="",
             max_result_size_chars=None, dynamic_schema_overrides=None,
             override=False):
    
    with self._lock:
        existing = self._tools.get(name)
        if existing and existing.toolset != toolset:
            # 不同工具集之间冲突：检查是否允许覆盖
            if both_mcp:
                pass  # MCP 服务器刷新是合法的
            elif override:
                # 插件显式要求覆盖 → 需要 operator 许可
                if plugin and not plugin_override_policy:
                    raise PermissionError(...)
            else:
                # 拒绝静默覆盖
                logger.error("REJECTED: would shadow existing tool")
                return  # ← 静默失败！
        
        self._tools[name] = ToolEntry(
            name=name, toolset=toolset, schema=schema, handler=handler,
            check_fn=check_fn, ...
        )
        self._generation += 1  # ← 每次注册都升级世代
```

这里有个有意思的设计决策：**静默失败**。当注册冲突时不是抛异常，而是 log error + return。为什么？因为工具文件是按字母顺序被 `discover_builtin_tools()` 导入的——`approval_tool.py` 和 `approval_tool.py`（如果有两个同名注册）不应该让整个系统崩溃。

### 4.2 check_fn 的瞬态失败容忍

这是之前提到的那个 Docker 超时不把工具"弄丢"的保护机制：

```python
_CHECK_FN_TTL_SECONDS = 30.0       # 缓存 30 秒
_CHECK_FN_FAILURE_GRACE_SECONDS = 60.0  # 最后一次成功后的容忍窗口

def _check_fn_cached(fn):
    now = time.monotonic()
    
    # 先查缓存
    with lock:
        cached = _check_fn_cache.get(fn)
        if cached and now - cached[0] < _CHECK_FN_TTL_SECONDS:
            return cached[1]  # 缓存命中
    
    # 实际执行检查
    try:
        value = bool(fn())
    except Exception:
        value = False
    
    with lock:
        if value:
            _check_fn_last_good[fn] = now
            _check_fn_cache[fn] = (now, True)
            return True
        
        # ← 重点：检查失败但在宽容期内 → 返回上次的成功结果
        last_good = _check_fn_last_good.get(fn)
        if last_good and now - last_good < _CHECK_FN_FAILURE_GRACE_SECONDS:
            return True  # 当成瞬态失败，不缓存失败结果
        
        # 真·失败
        _check_fn_cache[fn] = (now, False)
        return False
```

### 4.3 Tool Search 桥接

Hermes 有个很有意思的优化叫 **Tool Search**（渐进式工具发现）。当可用的 MCP 和插件工具太多时（占用大量 schema 空间），它把它们"推迟"到桥接工具后面：

```python
# model_tools.py (简化)
if ts_cfg.enabled != "off":
    # 核心工具 → 直接暴露
    # 非核心工具 → 移到 tool_search / tool_describe / tool_call 后面
    # 模型调 tool_search("找文件操作工具") → 返回 schemas
    # 模型调 tool_call("search_files", args) → 桥接到真正的工具
```

这样，模型在每轮对话中不需要传输几十个不常用的工具 schemas，省 token 省成本。

> 💭 **深度思考题**：check_fn 的宽容期为什么是 60 秒而不是 0？如果完全取消宽容期会有什么真实场景的问题？

---

## 第五层：关联 — 跟别的部分有什么联系？

### 5.1 Agent 循环 → Tools → 模型

还记得我们在 `teach-2-agent-loop.md` 里学的 agent 循环吗？

```
用户消息 → LLM → Tool Call → handle_function_call() → 结果 → LLM → 回复
                        ↑
                 model_tools.py 是关键桥梁
```

Agent 循环完全不知道工具的具体实现——它只调用 `registry.dispatch(name, args)`，然后获取 JSON 字符串结果。这种**松耦合**设计让工具可以独立演进，Agent 核心不需要随每个工具的变化而变化。

### 5.2 插件系统 → 工具系统

插件可以注册新工具！`hermes_cli/plugins.py` 的 `PluginManager` 提供了一个 `ctx.register_tool()` 方法：

```python
# 在 ~/.hermes/plugins/myplugin/__init__.py 里
def register(ctx):
    ctx.register_tool(
        name="my_custom_tool",
        toolset="custom",
        schema={...},
        handler=my_handler,
    )
```

**和内置工具有什么区别？** 完全没有！插件注册的工具也走 `registry.register()`，也受 check_fn、中间件、安全策略的约束。这就是"窄腰"的体现——插件不是二等公民。

### 5.3 MCP 服务器的桥接

MCP 模型上下文协议服务器也是通过 registry 集成的：

```python
# tools/mcp_tool.py - MCP 发现流程
async def discover_mcp_tools():
    config = load_mcp_config()  # 读取 mcp.servers 配置
    for name, server_cfg in config.items():
        tools = await mcp_client.list_tools(server_cfg)
        for tool in tools:
            registry.register(
                name=tool.name,
                toolset=f"mcp-{name}",  # ← 前缀 mcp- 防止冲突
                schema=tool.schema,
                handler=mcp_wrapper(name, tool.name),  # ← 通过 MCP 调用
            )
```

### 5.4 回到"先问再做"哲学

看看本任务的核心纪律里的 "先问再做，小步快跑"——这和 Hermes 的工具体系设计是对应的：

- **Automatic discovery（自发现）** = 工具不用手动注册，系统自己找到它们
- **check_fn（环境检查）** = 只有在环境满足条件时才暴露工具（"没装 Docker 就不给你 terminal"）
- **approval middleware（审批中间件）** = 危险操作先问用户确认
- **MCP/inheritance（继承）** = toolsets 之间可以 extends，和本任务 phase 的"一单元推进"很像

> 💭 **终极思考题**：你现在知道了整个工具加载链路——从文件扫描到 schema 生成到执行分发。如果让你在 Hermes 里新加一个"执行 SQL 查询"的工具，你会把它放在核心工具还是扩展工具集？为什么？

---

## 下一站

deep_dive_tools 已完成！这趟下来你应该看懂了：

1. ✅ 工具如何自动发现和注册
2. ✅ 工具集如何分组合并
3. ✅ 执行前的安全检查链条
4. ✅ 缓存策略和瞬态失败容忍
5. ✅ 插件和 MCP 的集成方式

**\> 接下来你想继续深挖哪个模块？**（plugins / cron / gateway / skills & memory / 扫 upstream issues）

*（静默时段自动探索中，06:00 后可见本报告）*
