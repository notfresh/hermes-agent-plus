# Hermes 核心路径方法参数字典

> 任务001 扫描产出：核心循环 / 上下文压缩 / 工具执行 / Skill 加载 四大核心路径的关键方法签名与参数定义。
> 行号基线：hermes-agent-plus 当前 checkout（2026-08-07，CRLF 行尾）。
> 用途：快速查阅"某个大方法接收什么参数、各参数什么意思"，省去翻源码。
> 注意：行号随版本演进会变，精确位置以 grep 实测为准。

---

## 一、核心循环（agent/conversation_loop.py）

### 1.1 run_conversation —— 主循环入口（整个 Agent 的心脏）

- **位置**：`agent/conversation_loop.py:588`
- **签名**：
  ```python
  def run_conversation(
      agent,                                  # AIAgent 实例（持有全部运行时状态）
      user_message: Any,                      # 用户本次输入（str 或消息结构）
      system_message: str = None,             # 自定义系统提示词；覆盖 ephemeral_system_prompt
      conversation_history: List[Dict] = None,# 历史消息（多轮续聊时传入）
      task_id: str = None,                    # 任务唯一 ID；隔离并发任务的 VM，不传自动生成
      stream_callback: Optional[callable] = None,  # 流式回调：每段文本增量调一次；
                                                  #   TTS 管线用它提前开始生成音频；
                                                  #   None = 走非流式路径
      persist_user_message: Optional[Any] = None,  # 存入会话的"干净"用户消息
                                                  #   （与原始输入分离，避免存到敏感原文）
      persist_user_timestamp: Optional[float] = None,  # 用户消息的时间戳
      moa_config: Optional[dict[str, Any]] = None,     # Mixture-of-Agents 配置（实验特性）
  ) -> Dict[str, Any]
  ```

- **主循环条件**（:715）：
  ```python
  while (api_call_count < agent.max_iterations
         and agent.iteration_budget.remaining > 0) \
         or agent._budget_grace_call:
  ```
  三层护栏：API 调用次数上限 + 迭代预算余额 + 预算宽限调用。

- **单次迭代步骤**（行号速查）：
  | 步骤 | 行号 | 说明 |
  |------|------|------|
  | 中断检查 | 720 | `if agent._interrupt_requested:` |
  | 预算消耗 | 736 | `agent.iteration_budget.consume()` |
  | 构建请求 | 864-930 | `api_messages` 准备 |
  | LLM 调用 | 1436-1466 | `agent._interruptible_api_call()` |
  | 工具执行 | 4701-5055 | `finish_reason == 'tool_use'` |
  | 上下文压缩 | — | `agent._compress_context()`（超阈值时） |

- **退出条件**：
  | 条件 | 处理 |
  |------|------|
  | `finish_reason == 'stop'` | 提取文本回复，break |
  | `finish_reason == 'tool_use'` | 执行工具，continue |
  | `api_call_count >= max_iterations` | 退出循环 |
  | `agent._interrupt_requested` | 用户中断 |

---

## 二、上下文压缩（agent/context_compressor.py）

### 2.1 compress —— 压缩入口（五步算法主方法）

- **位置**：`agent/context_compressor.py:3271`
- **签名**：
  ```python
  def compress(
      self,
      messages: List[Dict[str, Any]],   # 当前全部消息（含 system/assistant/tool）
      current_tokens: int = None,       # 当前 token 数（不传则内部估算）
      focus_topic: str = None,          # 引导压缩主题：优先保留该主题信息、
                                        #   其余更激进压缩（灵感来自 Claude Code /compact）
      force: bool = False,              # True=清除摘要失败冷却立即重试（手动 /compress 用）；
                                        #   False=自动压缩路径
  ) -> List[Dict[str, Any]]             # 压缩后的消息列表
  ```

- **五步算法**（docstring 摘要）：
  1. 剪枝旧工具结果（廉价预处理，不调 LLM）
  2. 保护头部消息（system prompt + 首轮交换）
  3. 按 token 预算找尾部边界（约 20K tokens 最近上下文）
  4. 用结构化 LLM prompt 摘要中间轮次
  5. 重复压缩时迭代更新既有摘要
  - 压缩后清理孤儿 tool_call / tool_result 对，避免 API 收到不匹配 ID

### 2.2 should_compress —— 触发判断

- **位置**：`agent/context_compressor.py:1557`
- **签名**：
  ```python
  def should_compress(self, prompt_tokens: int = None) -> bool
  # prompt_tokens: 当前 prompt token 数（不传内部估算）
  # 返回 True = 超过压缩阈值
  ```
- **反抖动保护**：若最近两次压缩每次节省 <10%，跳过压缩
  （防止每次只删 1-2 条消息的无限循环，issue #40803）

### 2.3 _prune_old_tool_results —— 剪枝旧工具结果

- **位置**：`agent/context_compressor.py:1649`
- **签名**：
  ```python
  def _prune_old_tool_results(
      self,
      messages: List[Dict[str, Any]],      # 全部消息
      protect_tail_count: int,             # 尾部保留的消息条数（最近 N 条不剪）
      protect_tail_tokens: int | None = None,  # 尾部保留的 token 数（双保险）
  ) -> tuple[List[Dict[str, Any]], int]    # (处理后的消息, 剪掉的条数)
  ```
- **行为**：旧工具结果替换为一行信息性摘要（如 `[terminal] ran npm test -> exit 0, 47 lines`），
  并去重相同工具结果（读同一文件 5 遍只留最新）

### 2.4 _generate_summary —— LLM 结构化摘要

- **位置**：`agent/context_compressor.py:2144`
- **签名**：
  ```python
  def _generate_summary(
      self,
      turns_to_summarize: List[Dict[str, Any]],  # 待摘要的轮次消息
      focus_topic: Optional[str] = None,         # 引导主题（同 compress）
  ) -> Optional[str]                             # 摘要文本；全部尝试失败返回 None
  ```
- **行为**：结构化模板（Goal / Progress / Decisions / Resolved-Pending Questions /
  Files / Remaining Work）；有前次摘要时做增量更新而非从头摘要

### 2.5 _protect_head_size —— 保护头部

- **位置**：`agent/context_compressor.py:2874`
- **签名**：
  ```python
  def _protect_head_size(self, messages: List[Dict[str, Any]]) -> int
  # messages: 全部消息
  # 返回: 头部保护的消息条数（system 在 0 位 + _effective_protect_first_n()）
  ```

### 2.6 _find_tail_cut_by_tokens —— 尾部 token 预算切点

- **位置**：`agent/context_compressor.py:3148`
- **签名**：
  ```python
  def _find_tail_cut_by_tokens(
      self,
      messages: List[Dict[str, Any]],   # 全部消息
      head_end: int,                    # 头部结束位置（从 head_end 之后开始算尾部）
      token_budget: int | None = None,  # token 预算；默认 self.tail_token_budget
                                        #   = summary_target_ratio * context_length（随窗口自适应）
  ) -> int                              # 尾部起始索引
  ```
- **细节**：token 预算是主准则；有消息条数下限（最近轮次保留原样）；
  预算允许超 1.5x 避免切进超大消息（tool 输出、文件读取）内部

### 2.7 _sanitize_tool_pairs —— 孤儿 tool 对清理

- **位置**：`agent/context_compressor.py:2769`
- **签名**：
  ```python
  def _sanitize_tool_pairs(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]
  # messages: 全部消息
  # 返回: 清理后的消息（tool_call/tool_result 成对，孤儿被移除）
  ```

### 2.8 _align_boundary_forward / _align_boundary_backward —— 边界对齐

- **位置**：`agent/context_compressor.py:2847` / `:2899`
- **签名**：
  ```python
  def _align_boundary_forward(self, messages: List[Dict[str, Any]], idx: int) -> int
  # idx: 候选切点；返回: 向前对齐后的切点（不切在 tool 组中间）
  def _align_boundary_backward(self, messages: List[Dict[str, Any]], idx: int) -> int
  # idx: 候选切点；返回: 向后对齐后的切点
  ```

---

## 三、工具执行（agent/tool_executor.py）

### 3.1 execute_tool_calls_concurrent —— 并发执行

- **位置**：`agent/tool_executor.py:327`
- **签名**：
  ```python
  def execute_tool_calls_concurrent(
      agent,                        # AIAgent 实例
      assistant_message,            # assistant 消息（含 .tool_calls）
      messages: list,               # 消息列表（结果按原顺序追加）
      effective_task_id: str,       # 生效的任务 ID（隔离 VM/上下文）
      api_call_count: int = 0,      # 当前 API 调用计数（预算核算用）
      *,                            # 以下仅关键字
      finalize: bool = True,        # False=跳过批次末尾聚合预算强制 + /steer 注入；
                                    #   用于混合批次中的一段（由分段分发器负责回合收尾）
  ) -> None
  ```
- **行为**：线程池并发执行多个 tool call；结果按原始调用顺序收集后追加

### 3.2 execute_tool_calls_sequential —— 顺序执行

- **位置**：`agent/tool_executor.py:1028`
- **签名**：
  ```python
  def execute_tool_calls_sequential(
      agent, assistant_message, messages: list,
      effective_task_id: str, api_call_count: int = 0, *,
      finalize: bool = True,
  ) -> None
  # 参数语义同 3.1；逐个执行，天然有序
  ```

### 3.3 execute_tool_calls_segmented —— 分段执行（混合批次）

- **位置**：`agent/tool_executor.py:1742`
- **签名**：
  ```python
  def execute_tool_calls_segmented(
      agent, assistant_message, messages: list,
      effective_task_id: str, api_call_count: int = 0,
      segments=None,               # 分段定义（哪些并发/哪些顺序）
  ) -> None
  ```

---

## 四、Skill 加载（agent/skill_utils.py + tools/skill_manager_tool.py）

### 4.1 _find_skill —— 按名查找 skill

- **位置**：`tools/skill_manager_tool.py:605`
- **签名**：
  ```python
  def _find_skill(name: str) -> Optional[Dict[str, Any]]
  # name: skill 名（对应目录名）
  # 返回: {"path": Path} 或 None
  ```
- **行为**：先搜本地 `~/.hermes/skills/`，再搜 `skills.external_dirs` 配置的外部目录；
  用 `rglob("SKILL.md")` 遍历，目录名匹配即命中

### 4.2 iter_skill_index_files —— 遍历 skill 索引文件

- **位置**：`agent/skill_utils.py:797`
- **签名**：
  ```python
  def iter_skill_index_files(skills_dir: Path, filename: str)
  # skills_dir: 技能根目录
  # filename: 要匹配的文件名（如 "SKILL.md"）
  # 产出: 排序后的匹配路径生成器
  ```
- **行为**：`os.walk(followlinks=True)`（穿透符号链接）；排除 Hermes 元数据、
  VCS、虚拟环境/依赖、缓存目录；支持目录（references/templates/assets/scripts）
  不算 skill 根（是渐进披露数据，经 skill_view(file_path=...) 加载）

### 4.3 load_skills_config —— 读技能配置

- **位置**：`agent/skill_preprocessing.py:25`
- **签名**：
  ```python
  def load_skills_config() -> dict
  # 返回: config.yaml 的 skills 段（best-effort，读不到返回空 dict）
  ```

---

## 五、补充：Skill 加载的完整调用链（001study 既有产出）

```
入口 skill_view() / /skill 命令
  └→ tools/skill_manager_tool.py  _find_skill(name)          # :605 定位 skill 目录
       └→ agent/skill_utils.py    iter_skill_index_files()   # :797 遍历 SKILL.md
            └→ agent/skill_preprocessing.py load_skills_config()  # :25 读配置
```

（更细的 skill 加载走读见 `walkthrough-1-skill-loading.md` 与 `walkthrough-2-skill-frontmatter.md`）

---

## 速查：文件 → 核心方法 → 行号

| 路径 | 方法 | 行号 |
|------|------|------|
| conversation_loop.py | run_conversation | 588 |
| context_compressor.py | should_compress | 1557 |
| context_compressor.py | _prune_old_tool_results | 1649 |
| context_compressor.py | _generate_summary | 2144 |
| context_compressor.py | _sanitize_tool_pairs | 2769 |
| context_compressor.py | _align_boundary_forward | 2847 |
| context_compressor.py | _protect_head_size | 2874 |
| context_compressor.py | _align_boundary_backward | 2899 |
| context_compressor.py | _find_tail_cut_by_tokens | 3148 |
| context_compressor.py | compress | 3271 |
| tool_executor.py | execute_tool_calls_concurrent | 327 |
| tool_executor.py | execute_tool_calls_sequential | 1028 |
| tool_executor.py | execute_tool_calls_segmented | 1742 |
| skill_manager_tool.py | _find_skill | 605 |
| skill_utils.py | iter_skill_index_files | 797 |
| skill_preprocessing.py | load_skills_config | 25 |
