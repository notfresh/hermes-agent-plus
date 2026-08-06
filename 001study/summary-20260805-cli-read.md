# 本次对话核心收获

> 2026-08-05 · hermes 代码探索

---

## 1. cli.py 结构数据

| 数字 | 含义 |
|------|------|
| 15903 | cli.py 总行数 |
| 298 | 函数总数 |
| 6 | 真正值得精读的函数 |
| 2500 | run() 行数 |
| 55 | run() 内部函数数 |

---

## 2. 查询流程核心路径

```
main() (15384)
   ↓
if query (15674) → cli.agent.run_conversation() (15793)
else → cli.run() (12749)
   ↓
handle_enter() (12991)
   ↓
_pending_input 队列 → process_loop() (14783)
   ↓
chat() (11590)
   ↓
agent.run_conversation() → agent/conversation_loop.py:588
```

---

## 3. 关键函数速查

| 行号 | 函数 | 作用 |
|------|------|------|
| 15384 | `main()` | CLI 入口 |
| 15674 | 分支判断 | 单次/交互 |
| 12749 | `cli.run()` | 交互主循环 |
| 12991 | `handle_enter()` | 按回车处理 |
| 14783 | `process_loop()` | 后台输入处理 |
| 11590 | `chat()` | 对话入口 |
| 588 | `run_conversation()` | Agent 引擎 |

---

## 4. 核心领悟

### 代码层面
- **AI 写的代码，只有 AI 能懂**
- **vibe coding = 快速生成 + 不重构 = 地狱阅读**
- **企业级 vs 原型：分层 vs 堆砌**

### 方法层面
- **用搜索代替线性阅读**
- **只读关键路径的 4-6 个位置**
- **其余遇到问题再查**
- **接受"不需要全部读懂"**

### 心态层面
- **问 AI 是正当技能**
- **不是你的问题，是代码的问题**
- **能跑就行，不用跟代码较劲**

---

## 5. 产出文档

1. [nav-cli-query-flow.md](nav-cli-query-flow.md) — 查询流程导航
2. [ReadCode-1-rant-cli-py-is-too-long.md](ReadCode-1-rant-cli-py-is-too-long.md) — 吐槽记录

---

## 6. 后续探索方向

- [ ] skill 加载链路
- [ ] 工具调用链路 (_execute_tool_calls)
- [ ] 消息渲染链路
- [ ] agent/conversation_loop.py 核心引擎
