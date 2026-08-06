---
name: record-method
description: "快速判断并记录一个方法是否是核心方法，存到 CSV"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [code-reading, methods, analysis]
    related_skills: [how-to-read-code]
---

# 记录方法重要性

## 用途

快速判断一个方法是否是核心方法，并记录到 CSV，方便后续查阅。

## 使用方法

告诉 Claude：
- 文件路径（如 `cli.py`、`hermes_cli/cli_agent_setup_mixin.py`）
- 行号或方法名

**自动执行**：Claude 会调用 `record_method.py` 脚本自动分析并写入 CSV。

## 自动分析规则

### 1. 方法名判断（初步）

| 模式 | 初步结论 |
|------|----------|
| `run / execute / do / chat / call` | 可能核心 |
| `ensure / check / init / install / prepare` | 可能边缘 |

**但别急着下结论！**

### 2. 必经节点判断（关键！）

**最重要的问题：这个方法是流程的必经节点吗？**

```
必经节点特征：
- 没有它，整个流程跑不起来
- 每个对话轮都会调用
- 处于关键路径上
```

例如 `_init_agent`：
- 方法名带 "init"（像边缘）
- 但它是 Agent 诞生的必经之路
- **→ 核心方法**

### 3. 守卫语句判断

```python
# 有这种 → 大概率边缘
if self._xxx:
    return
if getattr(self, '_xxx', False):
    return
```

### 4. 调用次数

```bash
grep -n "method_name(" *.py
```
- 10+ 次 → 核心
- 1-2 次 → 边缘

### 5. 综合判断

| 因素 | 核心 | 边缘 |
|------|------|------|
| 方法名 | run/execute/do | ensure/check/init |
| 必经节点？ | ✓ 是 | ✗ 否 |
| 调用频率 | 高 | 低 |
| 守卫语句 | 无 | 有 |

## 输出

CSV 文件: `001study/method_core_map.csv`

格式:
```
file,line,class,method,is_core,reason
cli.py,353,,AIAgent,YES,方法名含 run/execute/do
```

## 示例

```
# 记录 _init_agent
你: 帮我记录 hermes_cli/cli_agent_setup_mixin.py 第 226 行的方法

Claude: 已记录: _init_agent = 边缘方法
原因: 方法名含 ensure/check/init (边缘)
```
