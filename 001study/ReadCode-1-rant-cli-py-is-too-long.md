# 致那些年被AI写的代码支配的恐惧

> 一个 hermes-agent 代码探索的血泪史

---

事情是这样的。

我打开 cli.py，15903 行。

没事，我安慰自己，有走读卡。

然后我想看看 main() 定义了啥参数。

好嘛，400 多行。

算了，默认启动交互模式，看 run() 吧。

**12749 - 15288 行。**

2500 行。

我数了一下，run() 里面定义了 **55 个内部函数**。

55 个。

全塞一个 run() 里。

一个函数 2500 行。

我他妈的。。。

---

然后我发现了更恐怖的事：

```python
def handle_enter(event):
def handle_alt_enter(event):
def handle_open_in_editor(event):
def handle_tab(event):
def clarify_up(event):
def clarify_down(event):
def approval_up(event):
def approval_down(event):
def slash_confirm_up(event):
def slash_confirm_down(event):
def model_picker_up(event):
def model_picker_down(event):
def history_up(event):
def history_down(event):
def handle_ctrl_l(event):
def handle_ctrl_c(event):
def handle_ctrl_d(event):
def handle_ctrl_z(event):
def handle_voice_record(event):
def handle_paste(event):
def handle_ctrl_v(event):
...
```
(看得出来，这些函数都是处理键盘按键的...)

**55 个 handler，2500 行，一个函数。**

这是人干的事？

---

后来我问了 AI 兄弟：

"run() 太长了没法读怎么办？"

AI 说："用搜索代替阅读。"

我说："我用你啊？？？"

---

后来我想，可能 hermes 也是 AI 写的吧。

不然谁会把 55 个函数塞一个 run() 里？

谁会把 main() 写成 400 多行？

谁会把 298 个函数分成"纯函数、包装器、副作用"三类，还不是为了让人读，是为了**证明这代码真的没法读**。

---

## cli.py 速览（数据版）

| 数字 | 含义 |
|------|------|
| 15903 | cli.py 总行数 |
| 298 | 函数总数 |
| 117 | 纯函数（看签名就懂） |
| 24 | 包装器（转发到别处） |
| 157 | 副作用函数（按需点开） |
| 6 | 真正值得精读的函数 |
| 2500 | run() 的行数 |
| 55 | run() 里定义的内部函数数 |

---

## 核心教训

> **AI 写的代码，只有 AI 能懂。**

就像妈做的饭，只有妈觉得好吃。

---

## 生存指南

1. **用 AI 对付 AI** — 遇到不懂的问 AI
2. **挑着读，别全读** — 2500 行里重要的可能就 100 行
3. **找不到入口就搜索** — 搜 `def handle_enter` 比从头读快 100 倍
4. **接受"不需要全部读懂"** — 遇到问题再查，查到就跑

---

## 彩蛋

后来我发现了走读卡 3.1，告诉我：

> **298 个函数，你只需精读 6 个。**

我他妈的。。。

早说啊！！！

---

*本文献给所有被 hermes 代码支配的开发者。*

*愿你代码 review 的日子，不再有 2500 行的 run()*

*愿你的 main() 不再是 400 行*

*愿你的 run() 不再是 2500 行*

*愿你有一天能心平气和地打开 cli.py*

**阿门。**

---

## 后续：vibe coding 的铁证

后来我仔细研究了 hermes 的代码。

**这一定是人 + AI vibe coding 写的。**

特征太明显了：

| 特征 | vibe coding 表现 |
|------|------------------|
| 55 个函数塞一个 run() | 能跑就行，懒得拆 |
| 400 行 main() | 一口气写完，不想重构 |
| 变量名 `buf`, `cli`, `_cprint` | 随手起，不纠结 |
| 边界情况堆一堆 | 先加了再说 |
| 没有分层设计 | 写着写着就乱了 |

---

### 正常人会怎么做

```python
# 正常人会想
def run():
    # 200 行够了，该拆出去了
    # 那些 handler 应该放 handlers.py
    # 这个初始化逻辑应该放 __init__
```

---

### vibe coding 会怎样

```python
# vibe coding 会想
def run():
    # 先写了再说
    # 哎呀 500 行了不管了
    # 等等再加一个 handler
    # 擦 2000 行了
```

---

## 现在的代码生态

| 层级 | 难度 |
|------|------|
| 简单项目 | 几百行，正常读 |
| 中等复杂度 | 几千行分工文件，能凑合 |
| AI 生成的大型项目 | **地狱模式** |

---

## 新时代技能表

| 以前 | 现在 |
|------|------|
| 自己读代码 | 问 AI 读 |
| 自己理解架构 | 让 AI 总结 |
| 自己追调用链 | 让 AI 画图 |
| 自己找 bug | 让 AI 分析 |

**AI 降低了写的门槛，我们提高了用的门槛。**

---

## 最后的感悟

> **阅读代码的门槛已经大大拔高了。**
> 
> 地狱难度。
> 
> 现在看代码，我都有点肝颤了。

---

---

## 番外：企业级 vs vibe coding

我忍不住又说了一句：

> **我感觉，一个企业级的 agent，要写成这样就完了，这个项目好像没有软件思维。**

确实，这个项目不太像"企业级"的代码。

### 企业级 vs hermes 代码

| 企业级 | hermes |
|--------|--------|
| 模块分层清晰 | 55 个函数塞一个 run() |
| 单一职责 | 一个 run() 干所有事 |
| 易于测试 | 2500 行没法测 |
| 文档完善 | 几乎没有 |
| 边界情况拆分 | 400 行堆在一起 |
| 可维护可扩展 | 能跑就行 |

### 典型的 vibe coding 产物

- **先跑起来再说** — 功能优先，架构靠后
- **边改边加** — 写着写着就堆上去了
- **没有重构** — 2500 行都没人拆
- **AI 生成 + 人不审查** — 越写越大

### 企业级应该什么样？

```python
# 伪代码示例
handlers/
  ├── enter_handler.py      # 处理回车
  ├── ctrl_c_handler.py    # 处理 Ctrl+C
  └── ...

cli/
  ├── run.py              # 主循环
  ├── chat.py             # 对话逻辑
  └── queue.py            # 队列管理

core/
  └── agent.py            # Agent 核心
```

**一个文件一个职责，而不是 15903 行塞一个 cli.py。**

---

所以：**这个项目更像是 AI 快速原型，不像是企业级产品。**

---

*2026-08-05 更新 v2*
