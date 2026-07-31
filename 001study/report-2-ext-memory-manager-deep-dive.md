# 记忆管理器 (MemoryManager) 深度解析

> 本文档是对 `report-2-deep_dive_agent.md` 第 131-137 行的深度扩展，基于代码分析和实际示例，帮助理解 Hermes Agent 的记忆系统。

---

## 1. 核心概念澄清：记忆 vs 内存

| 术语 | 错误理解 | 正确理解 |
|------|---------|---------|
| Memory Manager | 内存管理器 | **记忆管理器** |
| Memory Store | 内存存储 | **记忆存储** |
| Memory Provider | 内存提供者 | **记忆提供者** |

> **关键点**：这里的 `Memory` 指的是 AI 的"长期记忆"，不是计算机的 RAM。记忆是持久化的，会跨会话保留。

---

## 2. 四大核心方法

### 2.1 `build_system_prompt()` — 构建系统提示词

**时机**：每次会话开始时（只执行一次）

**作用**：把记忆内容格式化成文本，塞进 AI 的系统提示词开头

**输出示例**：
```
══════════════════════════════════════════════════════
USER PROFILE (who the user is) [15% — 45/1375 chars]
══════════════════════════════════════════════════════
我是一个 Python 新手，喜欢简洁的代码

请用中文回复我
```

### 2.2 `prefetch_all()` — 预取相关记忆

**时机**：每次用户发消息时（每轮都执行）

**作用**：根据当前用户的问题，搜索相关记忆，返回给 AI 作为上下文

```
用户: "上次那个 bug 修好了没"
    ↓
prefetch_all() 搜索记忆库
    ↓
输出: "你上次提到的 bug 是 #123，发生在 user_controller.py..."
    ↓
一起送给 AI 模型
```

### 2.3 `sync_all()` — 同步本轮对话

**时机**：AI 回复后，后台执行

**作用**：把本次对话内容保存到记忆系统

**特点**：后台线程执行，不会阻塞用户

### 2.4 `queue_prefetch_all()` — 异步预取

**时机**：AI 回复后，后台执行

**作用**：预取下一轮可能用到的记忆，提升体验

---

## 3. 记忆提供者 (MemoryProvider) 全景

### 3.1 内置：MemoryStore

**存储位置**：`~/.hermes/memories/`

```
memories/
├── MEMORY.md   # Agent 的笔记（项目、工具、环境）
└── USER.md     # 用户的资料（偏好、沟通方式）
```

**启用配置**：
```yaml
memory:
  memory_enabled: true        # 启用 MEMORY.md
  user_profile_enabled: true  # 启用 USER.md
```

### 3.2 外部插件（8 种）

| Provider | 特点 |
|----------|------|
| **hindsight** | 知识图谱 + 语义搜索 + LLM 合成 |
| **honcho** | 向量语义搜索 |
| **mem0** | 向量语义搜索 |
| **supermemory** | 向量语义搜索 |
| **retaindb** | 向量语义搜索 |
| **holographic** | 向量语义搜索 |
| **openviking** | 向量语义搜索 |
| **byterover** | 向量语义搜索 |

### 3.3 重要约束

> **只允许一个外部提供者同时激活**

代码逻辑：
```python
def add_provider(self, provider: MemoryProvider) -> None:
    is_builtin = provider.name == "builtin"

    if not is_builtin:
        if self._has_external:
            # 拒绝第二个外部提供者！
            logger.warning("Rejected memory provider '%s' — external provider '%s' is already registered.")
            return
        self._has_external = True
```

**原因**：防止工具架构膨胀，减少冲突

---

## 4. 对话历史 vs 记忆系统

| | 对话历史 | 记忆系统 |
|---|---|---|
| **内容** | 这轮会话的聊天记录 | 跨会话的长期记忆 |
| **发送方式** | 每次 API 调用直接发送 | 通过 `prefetch_all()` 检索后发送 |
| **管理方式** | LLM SDK / Agent 框架 | MemoryManager + Provider |

**注意**：
- 对话历史天然直接发送（但会压缩/截断）
- 记忆需要主动检索（`prefetch_all`）

---

## 5. Hindsight 详解

### 5.1 三种运行模式

| 模式 | 说明 | 需求 |
|------|------|------|
| Cloud | 连接 Hindsight 云端 API | API Key |
| Local Embedded | 本地守护进程 + 内置 PostgreSQL | LLM API Key |
| Local External | 连接自托管实例 | 已运行的 Hindsight URL |

### 5.2 核心能力

- **retain** — 自动保存对话 + 实体提取
- **recall** — 语义搜索 + 知识图谱检索
- **reflect** — LLM 驱动的跨记忆合成

### 5.3 工具

| 工具 | 功能 |
|------|------|
| `hindsight_retain` | 存储信息，自动提取实体 |
| `hindsight_recall` | 多策略搜索 |
| `hindsight_reflect` | 跨记忆合成 |

---

## 6. 文件位置速查表

| 内容 | 路径 |
|------|------|
| 记忆配置文件 | `~/.hermes/hindsight/config.json` |
| 内置记忆文件 | `~/.hermes/memories/MEMORY.md` |
| 内置记忆文件 | `~/.hermes/memories/USER.md` |
| Hindsight 日志 | `~/.hermes/logs/hindsight-embed.log` |

---

## 7. 流程图：一次完整对话

```
会话开始
    │
    ├─► build_system_prompt() ──► 系统提示词（固定不变）
    │
    ▼
用户发消息 (Round N)
    │
    ├─► prefetch_all() ──► 搜索相关记忆 ──► 送给 AI
    │
    ▼
AI 回复
    │
    ├─► sync_all() ──► 后台保存到记忆系统
    │
    ├─► queue_prefetch_all() ──► 后台预取下一轮记忆
    │
    ▼
用户发消息 (Round N+1)
    │
    ...
```

---

## 8. 参考资料

- [memory_manager.py](agent/memory_manager.py) — 记忆管理器主实现
- [memory_provider.py](agent/memory_provider.py) — Provider 接口定义
- [memory_tool.py](tools/memory_tool.py) — 内置 MemoryStore 实现
- [plugins/memory/hindsight/](plugins/memory/hindsight/) — Hindsight 插件
