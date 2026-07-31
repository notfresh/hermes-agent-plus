# 教学 4：Hermes 插件系统

## 一句话

Hermes 的插件系统是一个 **四源发现 + 两阶加载 + 20+ 生命周期钩子**的扩展架构。插件可以注册工具、挂钩子、加中间件、注册 CLI/slash 命令、替换可插拔后端，全部通过 PluginContext 统一 facade。

---

## 1. 四大插件来源（四源发现）

```python
# plugins.py:1317-1371
# 优先级：后发现的覆盖先发现的同名插件
# 来源1：仓库自带 plugins/<name>/
repo_plugins = get_bundled_plugins_dir()
bundled = self._scan_directory(repo_plugins, source="bundled")

# 来源2：~/.hermes/plugins/<name>/
user_dir = get_hermes_home() / "plugins"
user_manifests = self._scan_directory(user_dir, source="user")

# 来源3：./.hermes/plugins/<name>/（需环境变量启用）
project_manifests = self._scan_directory(project_dir, source="project")

# 来源4：pip 安装，通过 hermes_agent.plugins entry-point
ep_manifests = self._scan_entry_points()
```

- **Bundled** — 仓库自带的安全插件，自动加载
- **User** — 用户安装，需 `plugins.enabled` 白名单
- **Project** — 项目级（你启用了才扫描）
- **Entrypoint** — pip install 的第三方插件

**同名覆盖规则**：user > bundled, project > user, entrypoint > bundled

---

## 2. 五种插件类型（kind）

| Kind | 加载策略 | 典型例子 |
|------|---------|---------|
| `standalone` | 白名单 opt-in | disk-cleanup, security-guidance |
| `backend` | 内置自动加载，用户需 opt-in | image_gen/openai, tts/openai |
| `exclusive` | 由 `<category>.provider` 配置选择 | memory/honcho, memory/mem0 |
| `platform` | 内置自动注册（延迟加载），用户 opt-in | telegram, discord, feishu |
| `model-provider` | 由 `providers/__init__.py` 管理 | 第三方 LLM 提供商 |

**自动检测机制**（`_parse_manifest` 最后做 heuristic 识别）：
- `__init__.py` 含 `register_memory_provider` → 自动归类为 `exclusive`
- 含 `register_provider` + `ProviderProfile` → 自动归类为 `model-provider`

---

## 3. 两阶加载策略

### 第一阶段：Manifest 扫描
PluginManager._scan_directory() 扫描目录，找 `plugin.yaml`，解析 PluginManifest

### 第二阶段：选择性加载
```
_discover_and_load_inner():
  1. 扫描所有来源的 manifests
  2. 去重（last writer wins）
  3. 对每个 manifest:
     a. plugins.disabled 黑名单 → 跳过
     b. kind == "exclusive" → 只记录，不加载（由 category 管理器处理）
     c. kind == "model-provider" → 只记录，由 providers/ 管理
     d. bundled + backend → 自动加载
     e. bundled + platform → 延迟加载（关键优化！）
     f. 其他 → 检查 plugins.enabled 白名单
```

### 延迟加载优化（关键设计）
```python
# plugins.py:1446-1447
# 20+ 内置平台插件（telegram/discord/feishu/teams...）都走延迟路径
if manifest.source == "bundled" and manifest.kind == "platform":
    self._register_deferred_platform(manifest)
```

为什么要延迟？每个平台 adapter 会 import 重型 SDK：
- `lark_oapi`（飞书）
- `discord.py`
- `slack_bolt`
- `microsoft_teams` ...
  
如果全部在 `hermes chat` 时 eager import，启动时间增加数秒。

解法：在 `platform_registry` 注册一个轻量 loader，首次请求该平台时才真正调 `_load_plugin()`。

---

## 4. PluginManifest -> LoadedPlugin 转化

```yaml
# plugins/disk-cleanup/plugin.yaml 示例
name: disk-cleanup
version: 2.0.0
description: "Auto-track and clean up ephemeral files..."
author: "@LVT382009 + NousResearch"
hooks:
  - post_tool_call
  - on_session_end
```

转化为 PluginManifest 数据类：
```python
@dataclass
class PluginManifest:
    name: str
    version: str = ""
    description: str = ""
    author: str = ""
    requires_env: List[Union[str, Dict]] = field(default_factory=list)
    provides_tools: List[str] = field(default_factory=list)
    provides_hooks: List[str] = field(default_factory=list)
    source: str = ""        # "bundled" | "user" | "project" | "entrypoint"
    path: Optional[str] = None
    kind: str = "standalone"
    key: str = ""           # 路径派生的 lookup key
```

加载后生成 LoadedPlugin（runtime 状态）：
```python
@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    module: Optional[ModuleType] = None
    tools_registered: List[str] = field(default_factory=list)   # 注册了哪些工具
    hooks_registered: List[str] = field(default_factory=list)
    middleware_registered: List[str] = field(default_factory=list)
    commands_registered: List[str] = field(default_factory=list)
    enabled: bool = False
    error: Optional[str] = None
    deferred: bool = False      # True = 延迟加载占位
```

---

## 5. PluginContext — 插件注册的核心 Facade

`PluginManager._load_plugin()` 的核心逻辑：
```python
# 1. 创建模块，导入 __init__.py
module = self._load_directory_module(manifest)

# 2. 获取 register() 函数
register_fn = getattr(module, "register", None)

# 3. 调用 register(ctx)，传递 PluginContext
ctx = PluginContext(manifest, self)
register_fn(ctx)

# 4. Diff 法统计注册内容
#    对比调用前后的 _plugin_tool_names / _hooks / _middleware
```

### PluginContext 提供的能力

| 方法 | 作用 | 底层 |
|------|------|------|
| register_tool() | 注册工具 | → tools.registry.register() |
| register_hook() | 注册生命周期钩子 | → self._hooks[name].append(cb) |
| register_middleware() | 注册中间件 | → self._middleware[name].append(cb) |
| register_cli_command() | 注册 CLI 子命令 | → self._cli_commands[name] |
| register_command() | 注册 slash 命令 | → self._plugin_commands[name] |
| register_skill() | 注册 skill | → self._plugin_skills[qn] |
| register_context_engine() | 替换上下文引擎 | 唯一注册（第二个被拒绝） |
| register_image_gen_provider() | 图生后端 | → image_gen_registry |
| register_tts_provider() | TTS 后端 | → TTS registry |
| register_browser_provider() | 浏览器后端 | → browser_registry |
| register_web_search_provider() | 搜索后端 | → web_search_registry |
| register_video_gen_provider() | 视频生成后端 | → video_gen_registry |
| register_secret_source() | 密钥管理器 | → secret_sources.registry |
| register_dashboard_auth_provider() | Dashboard 认证 | → dashboard_auth registry |
| register_auxiliary_task() | 辅助任务 | → self._aux_tasks |
| register_slack_action_handler() | Slack 交互 | → self._slack_action_handlers |
| dispatch_tool() | 通过 registry 调度工具 | → registry.dispatch() |
| inject_message() | 注入用户消息到对话 | → cli._interrupt_queue / _pending_input |
| llm (property) | 主机拥有的 LLM 访问 | → PluginLlm |
| profile_name (property) | 当前 profile 名称 | → get_active_profile_name() |

---

## 6. 生命周期钩子系统（20+ 个钩子点）

定义在 `VALID_HOOKS` 集合（plugins.py:135-215）：

```python
VALID_HOOKS = {
    # === 工具调用前后 ===
    "pre_tool_call",          # 工具执行前
    "post_tool_call",         # 工具执行后

    # === 输出变换 ===
    "transform_terminal_output",  # 终端输出变换（如脱敏）
    "transform_tool_result",      # 工具结果变换
    "transform_llm_output",       # LLM 输出变换（人格/词汇）

    # === LLM 调用 ===
    "pre_llm_call",           # LLM 调用前（可注入上下文）
    "post_llm_call",          # LLM 调用后

    # === API 请求 ===
    "pre_api_request",
    "post_api_request",
    "api_request_error",

    # === 会话生命周期 ===
    "on_session_start",
    "on_session_end",
    "on_session_finalize",
    "on_session_reset",

    # === 子 Agent ===
    "subagent_start",
    "subagent_stop",

    # === 网关 ===
    "pre_gateway_dispatch",   # 网关消息分发前（可跳过/改写）

    # === 审批 ===
    "pre_approval_request",   # 危险命令审批前（观察者模式，不可 veto）
    "post_approval_response",

    # === Kanban 看板任务 ===
    "kanban_task_claimed",    # 任务被认领
    "kanban_task_completed",  # 任务完成
    "kanban_task_blocked",    # 任务被阻塞

    # === 验证 ===
    "pre_verify",             # 代码编辑后验证前
}
```

**调用方式**：`invoke_hook(hook_name, **kwargs)` 遍历所有注册的回调，每个回调用 try/except 包裹，不信任插件不破坏核心。

**pre_llm_call 的特殊约定**：回调可返回 `{"context": "..."}` 注入到当前轮次的 user message 中（而非 system prompt），目的是保持 prompt cache 不变。

---

## 7. 安全隔离机制

| 层级 | 防护 |
|------|------|
| plugins.enabled 白名单 | 用户插件默认不加载 |
| plugins.disabled 黑名单 | 明确禁用 |
| plugins.entries.<id>.allow_tool_override | 插件替换内置工具需显式授权 |
| 内置插件信任 | bundled source 默认可 override |
| 钩子隔离 | 每个回调有独立 try/except |
| 目录级别 | 内存插件/上下文引擎自动检测分流 |

---

## 8. 插件目录结构

Flat 布局：
```
plugins/disk-cleanup/
├── plugin.yaml             # Manifests
├── __init__.py             # register(ctx) — 入口
├── disk_cleanup.py         # 实现逻辑
└── references/             # 其他资源
```

Category 布局（深度 ≤ 2 层）：
```
plugins/image_gen/
├── openai/
│   ├── plugin.yaml
│   └── __init__.py
├── google_imagen/
│   ├── plugin.yaml
│   └── __init__.py
└── ... (多个后端可选)
```

---

## 9. 完整注册流程（以 disk-cleanup 为例）

```
PluginManager.discover_and_load()
  → _scan_directory("plugins/")
    → 发现 plugins/disk-cleanup/plugin.yaml
    → _parse_manifest() → PluginManifest(name="disk-cleanup", kind="standalone")
  → 检查 plugins.enabled 白名单
  → _load_plugin(manifest)
    → _load_directory_module()
      → importlib 导入 plugins/disk-cleanup/__init__.py
      → 注册为 hermes_plugins.disk_cleanup 模块
    → register_fn = getattr(module, "register")
    → ctx = PluginContext(manifest, manager)
    → register_fn(ctx)
      → ctx.register_hook("post_tool_call", _on_post_tool_call)  → self._hooks["post_tool_call"].append(...)
      → ctx.register_hook("on_session_end", _on_session_end)
      → ctx.register_command("disk-cleanup", handler=..., ...)
    → 形成 LoadedPlugin(
        manifest=...,
        module=...,
        hooks_registered=["post_tool_call", "on_session_end"],
        commands_registered=["disk-cleanup"],
        enabled=True,
      )
    → self._plugins["disk-cleanup"] = loaded
```

---

## 10. 发现的设计亮点

1. **四源发现 + 同名覆盖** — 用户插件可以完全替换内置插件，不用改核心代码
2. **延迟加载（Deferred Loading）** — 20+ 平台插件的重型 SDK 不阻塞纯 CLI 启动
3. **Diff 法统计注册** — 通过 snapshot 前后对比精确归因每个插件注册的内容
4. **安全检查链** — 白名单 > 黑名单 > 类型识别 > override 许可 > try/except
5. **Namespace 管理** — 插件模块注册为 `hermes_plugins.<slug>` namespace，防冲突
6. **自动分类 heuristic** — 扫描 `__init__.py` 文件头 8K 识别插件类别
7. **Type-safe Provider 注册** — 每个 provider 类型有 ABC 校验，错误类型被静默拒绝

### 关键代码位置

| 功能 | 文件 | 行号 |
|------|------|------|
| PluginManager 核心 | `hermes_cli/plugins.py` | 1248-2023 |
| PluginContext | `hermes_cli/plugins.py` | 339-850 |
| 插件发现路由 | `hermes_cli/plugins.py` | 1317-1469 |
| 延迟加载平台 | `hermes_cli/plugins.py` | 1707-1746 |
| 钩子调用 | `hermes_cli/plugins.py` | 1892-1927 |
| 顶层入口 | `hermes_cli/plugins.py` | 2040-2054 |
| 插线入口 | `hermes_cli/subcommands/plugins.py` | 1-106 |
| 并发工具类 | `plugins/plugin_utils.py` | 1-136 |
| 示例插件 | `plugins/disk-cleanup/__init__.py` | 1-317 |
