# Hermes 数据存储

## 默认数据目录

**`~/.hermes/`** — 硬编码路径（`hermes_constants.py:52`），不遵循 XDG 规范。

```
~/.hermes/
├── config.yaml          # 主配置
├── .env                 # 用户环境变量
├── .hermes_history      # 对话历史
├── state.db             # 状态数据库 (47MB)
├── kanban.db            # 看板数据库
├── cache/ logs/ sessions/ skills/ plugins/ cron/ data/ memories/ ...
└── ... (共约 24 项子目录/文件)
```

## `./hermes` 源码路径

**是，使用本项目源码。**

- `hermes` 脚本直接 `from hermes_cli.main import main`
- `hermes_cli/main.py` 在启动时会 `sys.path.insert(0, str(PROJECT_ROOT))`（第 342-343 行）强制优先使用本项目源码

所以从项目目录 `./hermes` 启动，运行的是 `hermes-agent-plus/hermes_cli/` 下的代码。

> 另一份独立安装副本在 `/usr/local/lib/hermes-agent/`，内容有差异。

## 自定义数据目录

支持 `HERMES_HOME` 环境变量覆盖：

```bash
HERMES_HOME=/path/to/data ./hermes
```

解析优先级：
1. ContextVar 覆盖（per-task）
2. `HERMES_HOME` 环境变量
3. `~/.hermes` 默认（Windows: `%LOCALAPPDATA%\hermes`）

## 关键代码位置

- 路径解析核心：`hermes_constants.py:46-191`
- `.env` 加载：`hermes_cli/env_loader.py:288-338`
- `HERMES_HOME` 读取：`hermes_constants.py:107-132`
