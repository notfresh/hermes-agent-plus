# uv 包管理与虚拟环境

Hermes 项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖和虚拟环境，取代了传统的 `pip` + `venv`。

## 核心文件

| 文件 | 作用 |
|------|------|
| `pyproject.toml` | 直接依赖清单（精确锁定 `==X.Y.Z`） |
| `uv.lock` | 全量锁定文件（所有直接和传递依赖的 hash、来源等） |
| `.venv/` | uv 据此生成本地虚拟环境 |

依赖策略：所有直接依赖全部用 `==X.Y.Z` 精确锁定，不允许范围，以避免 PyPI 投毒自动流入。

Python 版本约束：`>=3.11, <3.14`（上限因 pydantic-core 等 Rust 依赖在 3.14 缺少 cp314 wheel）。

## 常用命令

### 环境管理

```bash
# 创建虚拟环境
uv venv --python 3.13

# 激活
source .venv/bin/activate

# 根据 pyproject.toml + uv.lock 同步环境
uv sync

# 只补齐缺失的包，不删多余的
uv sync --inexact
```

### 依赖管理

```bash
# 添加依赖（自动更新 pyproject.toml + uv.lock）
uv add httpx

# 添加开发依赖
uv add --dev pytest

# 移除依赖
uv remove httpx

# 查看已安装的包
uv pip list

# 查看依赖树
uv tree
```

### Python 版本管理

```bash
# 查看 uv 管理的 Python
uv python list

# 安装指定版本（uv 自动下载）
uv python install 3.13

# 创建 venv 时指定 Python
uv venv --python 3.13
```

### 其他

```bash
# 只更新锁文件，不安装
uv lock

# 不用激活 venv，直接跑
uv run python -c "print('hello')"
uv run pytest tests/
```

## 探测优先级

测试脚本 `scripts/run_tests.sh` 按以下顺序查找 venv：

1. `.venv/`（首选）
2. `venv/`（后备）
3. `~/.hermes/hermes-agent/venv`（worktree 共享场景）

## 快速速查

| 目标 | 命令 |
|------|------|
| 创建 venv | `uv venv --python 3.13` |
| 同步依赖 | `uv sync` |
| 加包 | `uv add <pkg>` |
| 删包 | `uv remove <pkg>` |
| 更新锁 | `uv lock` |
| 查看依赖树 | `uv tree` |
