# VSCode 中 Python 断点调试

## 1. 必要前提

- 安装 **Python 扩展**（MS Python extension）
- 打开快引用：`Ctrl+P` → 输入 `ext install ms-python.python`
- 选择正确的解释器：`Ctrl+Shift+P` → `Python: Select Interpreter` → 选 `.venv` 或系统 Python

## 2. 设置断点

- **点击行号左侧**的空白处，出现红点即设置成功
- 再次点击取消断点
- 右键红点可设置**条件断点**（满足条件才停）、**日志点**（不打断，只打印）

## 3. 启动调试

**方式 A — F5 傻瓜式（推荐入门）**
- 打开要调试的 `.py` 文件，直接按 `F5`
- VSCode 会提示并自动生成 `.vscode/launch.json`（选 `Python Debugger` → `Python File`）

**方式 B — 带工程配置的调试**
在 `.vscode/launch.json` 里写：
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: 当前文件",
            "type": "debugpy",
            "request": "launch",
            "program": "${file}",
            "console": "integratedTerminal"
        }
    ]
}
```
然后 `F5` 或点左侧「运行和调试」面板里的绿色播放键。

## 4. 常用调试操作（运行到断点后）

| 操作 | 快捷键 | 作用 |
|------|--------|------|
| 继续 | `F5` | 运行到下一个断点 |
| 单步跳过 | `F10` | 执行当前行，不进入函数 |
| 单步进入 | `F11` | 进入函数内部 |
| 单步跳出 | `Shift+F11` | 跳出当前函数 |
| 重启 | `Ctrl+Shift+F5` | 重新调试 |
| 停止 | `Shift+F5` | 结束调试 |

## 5. 调试面板（左侧「运行和调试」）

- **变量区**：查看所有局部/全局变量，悬停也能看
- **监视区**：右键添加表达式，实时跟踪（如 `self.count`）
- **调用堆栈**：看当前调用链，点击可跳转到上层函数
- **调试控制台**：在断点处临时执行表达式/命令

## 6. 关键小技巧

- **调试控制台**里可直接验证逻辑，甚至修改变量值：
  ```
  input_list.append(5)   // 直接在堆栈暂停状态执行
  ```
- **日志点**用于不打断运行但看中间值（模拟 print，但不用改代码）
- 若要调试的是 **脚本的某个函数**而非整个文件，可用 `"justMyCode": true` 只停在自己代码（默认已开启，跳过 `site-packages`）
- 断点设在不生效的行（如 `def` 定义行、注释、空行）VSCode 会提示"未验证的断点"

---

# 多文件调试（a.py 引用 b.py）

## 核心原理

**断点不会跨文件失效** —— VSCode 的调试是**基于进程的**：调试器 attach 到整个 Python 进程上，无论进程执行到哪个文件（`a.py` 的代码、`b.py` 里的函数，甚至 `site-packages` 里的库），只要设置了断点，执行到那一行就会停住。所以你完全可以在 `b.py` 里也点红点，`a.py` 调用到它时自然会停下来。

关键区别只在于**怎么启动调试**（入口文件是哪个）。

## 方案对比

| 场景 | 入口 | 做法 |
|------|------|------|
| 入口是 `a.py`（只是引用了 b） | `a.py` 按 F5 | 在 `a.py` 和 `b.py` 里都设断点，直接跑，`b.py` 的断点照样触发 |
| 入口是 `b.py`，但它有参数/被库调用 | 有 `if __name__ == "__main__"` 的那一个 | 调试那个文件 |
| 用 pytest 测试驱动 | 需要特殊配置 | 见下方「调试 pytest」 |

## 具体操作

**最常见情况 — 从入口文件启动即可**

```
a.py  (入口，被 F5 启动)
  └─ import b
      └─ b.py:def helper()   ← 在 b.py 这里设断点，a.py 调用时会停住
```

1. 打开 `a.py`，按 `F5`。
2. 别忘了在 `b.py` 的函数里也设置断点。
3. 当执行流进入 `b.py` 的断点行时，自动停下来，此时**调试面板的调用堆栈**会显示完整链条：`a.py 的某行 → b.py 的某行`。点堆栈里的任意帧可跳过去看那个文件的局部变量。

**`F11`（单步进入）的作用**
- 从 `b.helper(...)` 这一行按 `F11`，会直接跳进 `b.py` 的函数体，逐行调试。
- 若 `b.py` 是第三方库太多不想进，保持 `"justMyCode": true`，它会自动跳过库代码，只进你自己写的 `b.py`。

**调试 pytest 测试（多文件项目最常见的场景之一）**
1. 打开测试文件，按 `F5` → 选 `Python: Debug pytest`。
2. `.vscode/launch.json` 配置：
```json
{
    "name": "Python: 调试 pytest",
    "type": "debugpy",
    "request": "launch",
    "module": "pytest",
    "args": ["-q", "tests/test_b.py::test_something"],
    "console": "integratedTerminal"
}
```
3. 命中断点后，同样能跟着调用链跳进被 `test_` 调用的 `a.py` / `b.py` 源码。

## `launch.json` 补充：调试工作目录（cwd）

跨文件时 `program` 指向入口，但要确保 **`cwd`** 正确（相对导入 `from . import b` 依赖工作目录）：
```json
{
    "name": "Python: 调试入口",
    "type": "debugpy",
    "request": "launch",
    "program": "${workspaceFolder}/src/a.py",
    "cwd": "${workspaceFolder}",
    "console": "integratedTerminal"
}
```
`${workspaceFolder}` 是你的项目根目录（VSCode 打开的文件窗口根路径）。

---

# 命令行手动启动调试

## 方式 1：`python -m debugpy`（推荐，配合 VSCode）

把入口 `a.py` 跑在内嵌调试器下，断点由 VSCode 控制：

```bash
python -m debugpy --listen 5678 --wait-for-client src/a.py
```

- `--listen 5678`：debugpy 监听 5678 端口等待 VSCode 连接
- `--wait-for-client`：进程启动后**阻塞等** VSCode 连上来才执行（这样断点能提前设好）
- 去掉它则立即运行，VSCode 中途可连

VSCode 这边用「attach 模式」连上去：
```json
{
    "name": "Python: 附加远程调试",
    "type": "debugpy",
    "request": "attach",
    "connect": { "host": "localhost", "port": 5678 },
    "pathMappings": []
}
```
按 `F5` 选这个配置连上后，就能像正常 F5 一样用断点/`F10`/`F11`，并跟着调用堆栈在 `a.py`/`b.py` 之间跳。

**首次需要安装 debugpy**：`.venv` 里 `pip install debugpy`（MS Python 扩展一般已内置，若报没有则显式装一次）。

## 方式 2：脚本里埋 `debugpy` 代码（免 VSCode 手点启动）

在被调用的任意处（如 `b.py` 某函数开头）加：
```python
import debugpy
debugpy.listen(("localhost", 5678))   # 等待 VSCode 连接
```
无需 `--wait-for-client`，执行到这行它会自动阻塞，连接后在此处暂停。

## 方式 3：`pdb` 纯命令行（完全不用 VSCode）

在要停的位置插入 `breakpoint()`：
```python
for item in items:
    breakpoint()   # 停在这里，进入 pdb 交互
    result = process(item)
```
运行 `python a.py` 后停在断点处，终端命令：

| 命令 | 作用 |
|------|------|
| `n` (next) | 下一行（不进入函数） |
| `s` (step) | 进入函数 |
| `c` (continue) | 运行到下一个断点 |
| `p 变量名` | 打印变量 |
| `pp 变量名` | 美观打印 |
| `l` | 列出当前位置附近代码 |
| `w` | 查看调用栈 |
| `q` | 退出 |
| `!变量 = 值` | 修改变量值 |

`b.py` 里被调用的函数也能同样插 `breakpoint()`，自动跟随。

---

# VSCode 设置与避坑

## launch.json 里的关键字段

| 字段 | 作用 | 常见坑 |
|------|------|--------|
| `request` | `"launch"` = VSCode 自己启动程序；`"attach"` = 程序已在别处跑，VSCode 主动连上去 | attach 才有 `connect` |
| `program` | 入口脚本路径 | 用 `${file}` 时 = "打开哪个文件就跑哪个"，不是固定入口 |
| `args` | 传给脚本的命令行参数 | 数组形式 `["--flag", "值"]` |
| `module` | 用 `python -m <模块>` 方式启动（如 pytest） | 与 `program` 二选一 |
| `cwd` | 工作目录，影响相对导入 `from . import b` | 必须指向项目根，否则相对导入报错 |
| `env` | 额外环境变量（如 `PYTHONPATH`） | 只在 debug 时生效，手动命令行跑不带 |
| `justMyCode` | `true` = 只停自己代码，跳过 site-packages | 想审第三方库内部要设 `false` |
| `console` | 输出位置（`integratedTerminal` / `externalTerminal`） | 交互式输入需用集成终端 |
| `connect` / `pathMappings` | attach 时连的 host/port、路径映射 | 本地调试 `pathMappings` 留空 `[]` |

## 「F5 直接跑当前打开文件」的陷阱

VSCode 里 F5 具体跑哪个配置，取决于：

- **配置用 `${file}`** → 当前打开哪个 `.py`，就以它当入口跑。
- **有多个配置** → 正常应弹下拉让你选；但如果**之前选过某个配置，VSCode 会记住上次选择**，下次 F5 直接跑上次那个，不再弹窗——这正是"明明想看中间模块，却总按当前文件当入口跑了"的原因。

**避坑办法：**

1. **想要可控**：删掉用不到的配置，`launch.json` 只留一个你要的，F5 必然跑它。
2. **想每次都能选**：点顶部「运行和调试」面板左上角的下拉（显示当前配置名处），手动展开选目标配置，再点绿色 ▶，不依赖 F5 的记忆。
3. **入口固定**：需要"固定从 cli.py 启动、断点打在中间模块"时，把 `program` 写死为 `${workspaceFolder}/cli.py`，跟当前打开哪个文件无关。

## 调试中间模块（a.py 引用 b.py 的延伸）

**重要认知：调试入口 ≠ 当前打开的文件标签；断点设在哪，程序跑那就在那里停。**

- 入口文件决定"程序从哪开始"，断点决定"程序在哪停"。
- 调试被 `cli.py` 拉起的中间模块：断点设在中间模块里，但 F5 的 `request`/入口配置要指向 `cli.py`（否则会把中间模块当入口跑）。
- 若中间模块自身有 `if __name__ == "__main__":` 且能独立运行，则直接打开它、F5 以它当入口即可。

## 端口 5678 是不是固定的

**不是。** `5678` 只是 debugpy 的默认示例端口。

- 端口可换成任意未被占用的数字。
- 唯一要求：命令行 `--listen` 的端口 与 VSCode attach 配置里的 `connect.port` **必须一致**。
- 何时要换：端口被占（`Address already in use`）、同时调试多个进程（每个用不同端口）、容器/远程场景（要放行防火墙/转发规则）。

## 多进程 / 容器 / 远程调试建议

- **多进程**：每个进程一个端口，各配一个 attach 配置，逐个连接。
- **容器/Docker**：注意 `pathMappings`，把容器内路径映射到本地路径，VSCode 才能打开对应源码。
- **远程 SSH**：VSCode 的 Remote-SSH 会把整个窗口跑在远端，此时端口/路径都按远端看，`pathMappings` 通常可留空。

---

这个项目（`hermes-agent-plus`）用的是 Python，若有具体的文件调试需求，直接告诉我文件路径，我可以帮你定位并给出针对性的断点建议。
