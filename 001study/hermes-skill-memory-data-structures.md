# Hermes Skill 与 Memory 数据结构字典

> 任务001 扫描产出（续篇）：Skill 加载 / Memory 记忆 两条路径的核心数据结构。
> 行号基线：hermes-agent-plus 当前 checkout（2026-08-07，CRLF 行尾）。
> 配套文档：
> - 《hermes-core-methods-dictionary.md》——方法参数字典（核心循环/压缩/工具/skill）
> - 《hermes-core-data-structures.md》——核心循环/压缩/工具 数据结构
> 本文件：Skill 与 Memory 的数据结构 + 数据流转。

---

## 一、Skill 路径总览

Skill 体系**没有巨型类**，是"函数式 + 数据驱动"：核心数据结构是
**SKILL.md 文件（frontmatter + body）** 和加载过程中产生的各种 dict/枚举。
理解 skill 系统 = 理解 frontmatter 怎么被解析、过滤、注入。

```
SKILL.md 文件（磁盘）
  │  parse_frontmatter()        # skill_utils.py:123 拆出 frontmatter dict + body
  ▼
frontmatter dict（name/description/platforms/...）
  │  skill_matches_platform()   # 平台过滤 skill_utils.py:200
  │  skill_matches_environment()# 环境过滤 skill_utils.py:284
  ▼
SkillReadinessStatus 枚举       # skills_tool.py:224 就绪状态
  ▼
skill_view()                    # skills_tool.py:961 注入系统提示词
```

---

## 二、SKILL.md frontmatter —— Skill 的"身份证"

- **位置**：磁盘上每个 skill 目录下的 `SKILL.md`，解析入口 `agent/skill_utils.py:123`
- **一句话**：YAML frontmatter 是 skill 的全部元数据，body 是技能正文。
  frontmatter 解析失败 → 整个 skill 静默失效（name/description/平台门控全丢）。

### 解析结果结构

```python
parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]
# 返回 (frontmatter_dict, remaining_body)
```

### frontmatter 常见字段

| 字段 | 含义 | 用途 |
|------|------|------|
| name | skill 名（目录名必须一致） | 查找/引用 |
| description | 一句话描述 | 系统提示词注入、skills 列表展示 |
| platforms | 支持的平台列表（linux/macos/...） | skill_matches_platform 过滤 |
| languages | 适用语言 | 展示/过滤 |
| tags | 标签 | 搜索/分类 |
| required_environment_variables | 必需环境变量 | setup 提示（skills_tool.py:336 收集） |
| setup_needed | 是否需配置 | SkillReadinessStatus 判定 |
| created_by | 创建者（agent/hub/manual） | curator 生命周期管理 |

### 解析细节（为什么重要）

- **BOM 陷阱**：Windows 编辑器保存 UTF-8 会加 BOM（U+FEFF），
  不剥离则 `---` 围栏检查失败 → 整个 frontmatter 静默丢弃
  （name/description/平台门控/env 全没）。parse_frontmatter 先剥 BOM。
- **解析器**：yaml CSafeLoader（完整 YAML：嵌套、列表），
  失败回退简单 key:value 拆分（鲁棒性）。

---

## 三、SkillReadinessStatus —— Skill 就绪状态枚举

- **位置**：`tools/skills_tool.py:224`
- **一句话**：一个 skill 当前"能不能用"的三态判定，供系统提示词和 UI 展示。

### 枚举值

```python
class SkillReadinessStatus(str, Enum):
    AVAILABLE = "available"        # 就绪，可直接用
    SETUP_NEEDED = "setup_needed"  # 需要配置（缺环境变量等）
    UNSUPPORTED = "unsupported"    # 平台/环境不支持
```

### 判定链（数据流转）

```
SKILL.md → parse_frontmatter → frontmatter dict
  → skill_matches_platform(frontmatter)    # 平台不匹配 → UNSUPPORTED
  → skill_matches_environment(frontmatter) # 环境不匹配 → UNSUPPORTED
  → _get_required_environment_variables()  # 缺必需 env → SETUP_NEEDED
  → 全通过 → AVAILABLE
```

---

## 四、skill_view —— Skill 注入入口（函数）

- **位置**：`tools/skills_tool.py:961`
- **一句话**：把 skill 内容加载成系统提示词可用的消息（或返回 skill 内文件内容）。

### 签名

```python
def skill_view(
    name: str,                  # skill 名或路径（"axolotl" 或 "03-fine-tuning/axolotl"；
                                #   "plugin:skill" 解析到插件 skill）
    file_path: str = None,      # skill 内文件路径（references/api.md 等渐进披露文件）
    task_id: str = None,        # 任务标识（探测活动后端用）
    preprocess: bool = True,    # 是否应用 SKILL.md 模板 + 内联 shell 渲染；
                                #   内部 slash/preload 调用方传 False（自行渲染）
) -> str                        # JSON 字符串（skill 内容或错误信息）
```

### 数据流转

```
skill_view(name)
  → _find_skill(name)                       # skill_manager_tool.py:605 定位目录
  → iter_skill_index_files(dir, "SKILL.md") # skill_utils.py:797 遍历索引
  → 读 SKILL.md → parse_frontmatter → 过滤（平台/环境/禁用名单）
  → preprocess=True？ → 模板渲染 + 内联 shell 渲染
  → 返回 skill 内容（注入系统提示词）
```

---

## 五、Memory 路径总览

Memory 体系是"**Manager（编排） + Provider（后端抽象） + Store（内置存储）**"
三层结构。核心数据结构：

```
MemoryManager（编排）         agent/memory_manager.py:354
  ├→ List[MemoryProvider]     多个后端（内置 + 外部）
  ├→ _tool_to_provider        工具名 → 后端映射
  └→ 分发: handle_tool_call() / prefetch_all()

MemoryProvider（抽象）         agent/memory_provider.py:43
  └→ 各实现（内置 MemoryStore / Honcho / Mem0 ...）

MemoryStore（内置存储）        tools/memory_tool.py:113
  └→ memory_entries / user_entries 双列表 + 快照
```

---

## 六、MemoryManager —— 记忆编排器

- **位置**：`agent/memory_manager.py:354`
- **一句话**：管理所有记忆后端的"总调度"，负责注册、分发、预取、关闭。

### 职责与字段

| 字段 | 含义 |
|------|------|
| _providers | 已注册后端列表（List[MemoryProvider]） |
| _tool_to_provider | 工具名 → 后端映射（"memory" → 内置 Store） |
| _has_external | 是否已有外部后端（非内置） |
| _external_prefetch_threads | 外部预取线程表 |
| _external_prefetch_lock | 预取并发锁 |
| _sync_executor | 同步执行线程池 |
| _shutting_down / _shutdown_drain_state | 关闭状态与排空记录 |

### 核心方法

| 方法 | 行号 | 说明 |
|------|------|------|
| add_provider() | :394 | 注册后端（首个外部后端置 _has_external） |
| providers() | :463 | 返回全部后端 |
| get_provider(name) | :467 | 按名取后端 |
| build_system_prompt() | :476 | 汇总各后端 system_prompt_block |
| prefetch_all(query) | :515 | 并行预取（外部后端走线程） |
| handle_tool_call() | 分发 | 工具调用路由到对应后端 |

### 数据流转（一次记忆读写）

```
回合开始 → prefetch_all(query) → 各 provider.prefetch() 并行
  → build_system_prompt() → 各 provider.system_prompt_block() 拼进提示词
  → 模型调用 memory 工具 → handle_tool_call("memory", args)
      → _tool_to_provider["memory"].handle_tool_call(...)
  → 结果返回模型（写入/读取）
  → 回合结束 → on_turn_start / on_session_end 钩子通知各后端
```

---

## 七、MemoryProvider —— 记忆后端抽象接口

- **位置**：`agent/memory_provider.py:43`
- **一句话**：所有记忆后端的统一契约。内置 MemoryStore 是一个实现，
  Honcho/Mem0 等是外部实现。

### 接口方法（全部可由实现覆盖）

| 方法 | 行号 | 说明 |
|------|------|------|
| name() | :48 | 后端名 |
| is_available() | :54 | 可用性（缺依赖返回 False） |
| initialize(session_id, **kwargs) | :62 | 会话初始化 |
| system_prompt_block() | :85 | 返回注入系统提示词的文本块 |
| prefetch(query, *, session_id) | :94 | 同步预取（返回相关记忆文本） |
| queue_prefetch(query, *, session_id) | :108 | 异步入队预取 |
| sync_turn(...) | :116 | 回合同步 |
| get_tool_schemas() | :135 | 提供给模型的工具 schema 列表 |
| handle_tool_call(tool_name, args, **kwargs) | :144 | 工具调用处理 |
| shutdown() | :152 | 关闭 |
| on_turn_start / on_session_end / on_session_switch | :157-176 | 生命周期钩子 |
| on_pre_compress(messages) | :220 | 压缩前钩子（记忆内容在压缩中的处理） |

### 数据流转

```
MemoryManager.add_provider(MemoryStore(...))   # 注册
  → 模型调用工具 → manager 路由 → provider.handle_tool_call()
  → 生命周期事件 → provider.on_* 钩子（回合/会话/压缩）
```

---

## 八、MemoryStore —— 内置有界记忆存储

- **位置**：`tools/memory_tool.py:113`
- **一句话**：Hermes 默认记忆实现——**有界、带文件持久化、双状态**。
  这就是"我的记忆"功能背后的数据结构（当前会话的 memory 就长这样）。

### 职责与字段

| 字段 | 含义 |
|------|------|
| memory_entries | 个人笔记列表（List[str]，每条一个记忆） |
| user_entries | 用户画像列表（List[str]） |
| memory_char_limit | 个人笔记字符上限（默认 2200） |
| user_char_limit | 用户画像字符上限（默认 1375） |
| _system_prompt_snapshot | 加载时冻结的系统提示词快照（{memory, user}） |
| _consolidation_failures | 本回合合并失败计数 |

### 双状态设计（关键！）

```
_system_prompt_snapshot  ← 加载时冻结，永不中途修改
                          （保持前缀缓存稳定，prompt caching 神圣不可破）
memory_entries / user_entries ← 实时状态，工具调用修改，持久化到磁盘
                              （工具响应始终反映实时状态）
```

### 合并失败降级（#42405）

- `_MAX_CONSOLIDATION_FAILURES_PER_TURN = 3`
- 单回合内合并失败 ≤3 次：返回原响应（含自我纠正+重试指引）
- 超过 3 次：返回 **TERMINAL 结果**，模型停止循环 memory 调用、直接回答用户
  ——**记忆副作用绝不能阻塞回合回复**

### 数据流转（一次记忆写入）

```
模型调用 memory 工具（"记住：用户偏好 X"）
  → MemoryManager.handle_tool_call → MemoryStore.handle_tool_call()
  → 容量检查：memory_entries 总长 ≤ memory_char_limit？
      → 是：追加
      → 否：合并旧条目（consolidation）→ 失败计数++
  → 持久化到磁盘
  → 工具响应回模型（成功/合并失败指引）
```

---

## 九、StreamingContextScrubber —— 流式记忆上下文清洗器

- **位置**：`agent/memory_manager.py:172`
- **一句话**：流式输出时清洗可能跨 chunk 的 `<memory-context>` 跨度，
  防止记忆内容泄漏到 UI。**一次性正则搞不定分块边界**，用状态机跨 delta 处理。

### 用法

```python
scrubber = StreamingContextScrubber()
for delta in stream:
    visible = scrubber.feed(delta)   # 返回可见文本（跨度内的被吞掉）
    if visible:
        emit(visible)
trailing = scrubber.flush()          # 流结束时收尾
```

### 为什么需要它

`<memory-context>` 标签可能在 delta A 打开、delta B 关闭——
一次性正则只匹配单字符串内的完整标签对，跨 chunk 就漏了。
状态机：跨 delta 持有部分标签尾部，丢弃跨度内全部内容（含系统注记行）。

---

## 十、HermesCLI —— CLI 入口类（Skill/Memory 加载的顶层编排）

- **位置**：`cli.py:3703`
- **一句话**：交互式 CLI 的"总装车间"，继承三个 Mixin 承载全部命令处理。
  Skill 与 Memory 的初始化、配置、命令路由都在这个类里。

### 继承结构

```
HermesCLI
  ├→ CLIAgentSetupMixin   # agent 初始化/凭证解析/会话恢复
  ├→ CLICommandsMixin     # slash 命令处理器（/rollback, /snapshot 等）
  └→ CLIBillingMixin      # 计费/订阅处理（/topup, /subscription 等）
```

### 职责与字段

| 类别 | 字段/职责 |
|------|-----------|
| **配置** | model / provider / api_key / base_url / max_turns / enabled_toolsets / disabled_toolsets |
| **显示** | compact / tool_progress_mode / streaming_enabled / show_reasoning / show_timestamps / final_response_markdown |
| **会话** | session_id / conversation_history / session_start / _resumed |
| **Agent** | agent（AIAgent 实例，延迟初始化） |
| **存储** | _session_db（SessionDB，SQLite 会话持久化） |
| **状态** | _agent_running / _pending_input / _interrupt_queue / _should_exit |
| **Skill 相关** | personalities / prefill_messages / reasoning_config |
| **CLI 回调** | tool_progress_callback / stream_delta_callback / event_callback 等 |

### Skill/Memory 协作入口

```
用户启动 CLI
  → HermesCLI.__init__() 初始化配置
  → run() / chat() 进入交互循环
  → _init_agent() → AIAgent 初始化（此时 Skill/Memory 加载）
      └→ AIAgent 内部：MemoryManager.prefetch_all() / skill_view() 注入
  → slash 命令 → CLICommandsMixin._handle_*_command() 处理
  → 记忆操作 → 模型调用 memory 工具 → MemoryStore 响应
```

### Mixin 详情

| Mixin | 位置 | 职责 |
|-------|------|------|
| CLIAgentSetupMixin | hermes_cli/cli_agent_setup_mixin.py:22 | 运行时凭证解析、Agent 构建、会话恢复、历史展示 |
| CLICommandsMixin | hermes_cli/cli_commands_mixin.py:43 | 30+ slash 命令处理器（rollback/snapshot/title/steer 等） |
| CLIBillingMixin | hermes_cli/cli_billing_mixin.py:21 | Nous 计费：/topup /subscription /usage 全部流程 |

### 数据流（Skill/Memory 视角）

```
HermesCLI.run() / chat()
  ├→ _init_agent()           # 构建 AIAgent
  │     └→ AIAgent.__init__() → MemoryManager 初始化
  │                           → Skill 系统就绪（skill_view 可用）
  ├→ 用户输入 → process_command() 或 chat()
  │     ├→ slash 命令 → CLICommandsMixin._handle_*_command()
  │     └→ 普通消息 → agent.run_conversation()
  │           ├→ MemoryManager.prefetch_all()   # 记忆预取
  │           ├→ skill_view() 加载 Skill       # 技能注入
  │           └→ 模型调用 memory/skill 工具
  └→ 会话结束 → MemoryProvider.on_session_end()
```

---

## 速查：数据结构 → 职责一句话

| 数据结构 | 位置 | 一句话 |
|----------|------|--------|
| SKILL.md frontmatter | skill_utils.py:123 解析 | Skill 身份证：全部元数据 + 平台/环境门控 |
| SkillReadinessStatus | skills_tool.py:224 | 三态：available / setup_needed / unsupported |
| skill_view() | skills_tool.py:961 | Skill 注入入口（模板渲染 + 渐进披露） |
| MemoryManager | memory_manager.py:354 | 记忆总调度：注册/分发/预取/关闭 |
| MemoryProvider | memory_provider.py:43 | 记忆后端抽象契约（内置/外部统一接口） |
| MemoryStore | memory_tool.py:113 | 内置有界记忆：双列表 + 快照 + 持久化 |
| StreamingContextScrubber | memory_manager.py:172 | 流式跨 chunk 记忆跨度清洗状态机 |
| HermesCLI | cli.py:3703 | CLI 总装车间：三个 Mixin 编排全部交互逻辑 |

---

## Skill + Memory 与主循环的协作（数据流总览）

```
回合开始
  ├→ MemoryManager.prefetch_all(query)        # 记忆预取（并行）
  ├→ MemoryManager.build_system_prompt()      # 记忆块注入系统提示词
  ├→ skill_view(...) 加载技能（平台/环境过滤后）  # skill 注入
  ▼
主循环（run_conversation）
  ├→ 模型可能调用 memory 工具 → MemoryStore 读写（有界+持久化）
  ├→ 模型可能调用 skill 工具 → skill_view 渐进披露
  └→ 上下文超阈值 → ContextCompressor.compress()
        └→ MemoryProvider.on_pre_compress()   # 记忆在压缩中的特殊处理
  ▼
回合结束 → MemoryProvider.on_session_end()
```
