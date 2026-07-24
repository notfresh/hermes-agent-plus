# Hermes 项目启动入口

## 入口文件

| 入口 | 路径 | 说明 |
|------|------|------|
| **真正的 CLI 主入口** | `hermes_cli/main.py` | `main()` 函数（约第 13205 行） |
| **项目根目录包装脚本** | `./hermes` | 纯粹的 wrapper，实际调用 `hermes_cli.main:main` |
| **Agent 独立入口** | `run_agent.py` | `hermes-agent` 命令的入口 |

## 入口点配置（`pyproject.toml` 第 307-310 行）

```toml
[project.scripts]
hermes       = "hermes_cli.main:main"     # 主命令
hermes-agent = "run_agent:main"
hermes-acp   = "acp_adapter.entry:main"
```

## 重要文件说明

- `cli.py` — 751KB 的核心逻辑库，**不是入口文件**，被 `hermes_cli` 等调用
- `hermes` — 根目录 shell 启动器 wrapper，内容：

  ```python
  if __name__ == "__main__":
      from hermes_cli.main import main
      main()
  ```

## 启动命令

### 安装后使用

```bash
hermes              # 无参数 → 进入交互式 chat（默认行为）
hermes chat         # 交互式聊天
hermes model        # 选择 LLM 提供商/模型
hermes gateway      # 前台运行 gateway
hermes doctor       # 检查配置和依赖
hermes setup        # 交互式配置向导
```

### 从源码开发环境启动

```bash
# 方式 A：直接运行根目录启动器脚本
cd /root/projects/hermes-agent-plus
./hermes

# 方式 B：以模块方式运行主入口
python -m hermes_cli.main

# 方式 C：可编辑安装后使用 hermes 命令（贡献者标准流程）
uv pip install -e ".[all,dev]"
hermes
```

## `main()` 子命令

`hermes_cli/main.py` 中的 `main()` 函数负责解析以下子命令：

- `chat` — 交互式聊天（默认）
- `gateway` — 前台运行 gateway
- `cron` — 定时任务
- `doctor` — 检查配置和依赖
- `model` — 选择 LLM 提供商/模型
- `moa` — MOA 模式
- `acp` — ACP 适配器
