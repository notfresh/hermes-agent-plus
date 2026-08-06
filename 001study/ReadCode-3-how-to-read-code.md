# 代码阅读方法论

> 如何高效阅读大型代码库？边缘分支太多怎么办？
> 
> 核心原则：**代码是给人读的，不是让你背的。**

---

## 问题：边缘分支太多，看不完

每个函数/方法里 80% 是边缘分支，只有 20% 是主流程。
全部细读 → 迷失在细节里 → 忘了自己在哪。

---

## 原则 1：先区分「主路径」vs「边缘分支」

每个函数都有**最典型的使用场景**，先专注这个：

```python
def _prepare_deferred_agent_startup() -> None:
    global _deferred_agent_startup_done
    if _deferred_agent_startup_done:    # ← 已执行过，跳过
        return
    if os.environ.get("HERMES_DEFER_AGENT_STARTUP") != "1":  # ← 主路径：非 Termux 直接 return
        return
    # 下面都是 Termux 边缘分支...
```

**主路径就是这两行 `return`，后面的不用看。**

---

## 原则 2：用「跳板思维」

读代码像过河：

```
你 → 边缘分支(不重要的桥) → 对岸(继续主流程)
     ↑ 
     但你可以不过桥，直接游过去！
```

**技巧**：看到 `if xxx: return` 这种守卫语句，直接当它是「透明」的，跳过继续往下看。

---

## 原则 3：先读「调用点」再读「定义」

比如 `_prepare_deferred_agent_startup()`：

- **调用点**（mixin:238）：`_prepare_deferred_agent_startup()`
- **定义**（cli.py:950）：几百行

**正确的顺序**：
1. 知道它在哪被调用 → 哦，原来是初始化时调用
2. 知道它的返回值/副作用 → 哦，原来是延迟启动
3. **不需要深入细节**，除非你在调试这个功能

---

## 原则 4：画「流程图」而不是「代码翻译」

❌ 错误：把每行代码翻译成中文
✅ 正确：画关键节点

```
chat() 
  → _init_agent()
    → 前置检查 (跳过)
    → SessionDB (跳过)  
    → **AIAgent()** ← 核心，其他都是准备
```

**只记关键节点，不记细节。**

---

## 原则 5：需要的时候再查

> 代码是给人读的，不是让你背的。
> 
> 需要的时候再查，不需要一次性搞懂。
> 
> 边缘分支回头遇到 bug 再细看，现在**知道它在哪儿就行**。

---

## 实战技巧

### 1. 找「入口点」

```bash
# 搜索哪个函数被 main() 调用
grep -n "def main" cli.py
```

### 2. 找「调用链」

```bash
# 搜索某个方法在哪里被调用
grep -n "method_name(" cli.py
```

### 3. 用 IDE 跳转

- VS Code: `Cmd+Click` 跳转
- 记得回来：`Alt+Left`

### 4. 加日志/断点

如果还是不懂，加一行 print：

```python
print(f"DEBUG: _init_agent called with model={model_override}")
```

跑一下就知道实际走哪条分支了。

### 5. 先文档再代码

```bash
# 先看有没有文档
ls *.md
cat README.md
```

很多设计决策写在文档里，比代码容易懂。

---

## 快速检查清单

- [ ] 找到入口点了吗？
- [ ] 知道调用链了吗？
- [ ] 能画出关键节点了吗？
- [ ] 边缘分支标记出来了吗？
- [ ] 能用自己的话解释主流程吗？

---

## 常见问题

**Q: 看到一个函数几百行，想死怎么办？**
A: 先看前 10 行，很可能就是 `if xxx: return`，后面的边缘分支不用看。

**Q: 怎么知道哪个是主路径？**
A: 看「最常见的调用场景」——函数文档/注释会写，或者看 90% 的调用点走哪条分支。

**Q: 需不需要记每个变量的作用？**
A: 不用。记住关键的 3-5 个变量就行，其他的回头查。

---

## 技巧：如何判断「主路径」vs「边缘分支」

### 1. 看调用次数

```bash
grep -n "_ensure_runtime_credentials" cli.py hermes_cli/*.py
```

- 调用次数 **10+ 次** → 核心方法
- 调用次数 **1-2 次** → 边缘分支

### 2. 看「守卫语句」

```python
# 典型的边缘检查写法
def _ensure_runtime_credentials(self):
    if self._credentials_valid:    # ← 缓存检查
        return True
    # 真正的工作...
```

- 有 `if xxx: return` 快速返回 → **边缘检查**
- 没有，直接往下走 → **主路径**

### 3. 看方法名

| 命名模式 | 大概率是 |
|----------|----------|
| `ensure_xxx` | 检查/准备，边缘 |
| `check_xxx` | 检查，边缘 |
| `init_xxx` | 初始化，边缘 |
| `run_xxx` | **执行，主路径** |
| `execute_xxx` | **执行，主路径** |
| `do_xxx` | **执行，主路径** |

### 4. 看「副作用」

- 改全局状态、文件、数据库 → **可能重要**
- 只读检查、返回 True/False → 边缘

### 5. 实践判断示例：`_ensure_runtime_credentials`

```
调用位置：_init_agent() 里，第 242 行
    ↓
方法名：ensure_xxx → 边缘检查
    ↓
逻辑：如果凭证有效就返回 True，否则尝试刷新
    ↓
结论：主路径也会走，但只是「准备」，不是「核心执行」
```

---

## 技巧：Mixin 方法无法跳转？

Python 的 Mixin 没有「接口声明」，IDE 无法静态分析调用的方法在哪。

### 解决方案

```bash
# 1. 命令行跳转
grep -n "def _install_tool_callbacks" cli.py
# 输出: 6132:    def _install_tool_callbacks(self) -> None:

# 2. 记住「调用链地图」
_init_agent (mixin:226)
  ├─→ _install_tool_callbacks()       → cli.py:6132
  ├─→ _ensure_tirith_security()      → cli.py:6147
  └─→ _ensure_runtime_credentials()  → cli.py:???
```

---

*2026-08-05*
