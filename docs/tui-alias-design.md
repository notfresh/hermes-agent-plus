# TUI Alias 设计文档

> 用户自定义快速命令别名功能 — 从 kimi-code 移植 (kimi #3158)

## 概述

`tui-alias` 是 Hermes 的用户自定义命令别名系统，灵感来自 git-style alias。它允许用户创建短别名来快捷调用 slash 命令。

**核心特性：**
- 用户别名优先于内置命令
- 单跳展开防止循环引用
- 立即生效（无需重启）
- 支持别名链（`a → b → c`）
- 冲突警告

---

## 核心提交

| 提交 | 描述 |
|------|------|
| `fdb7aa441b` | feat: user-defined quick-command aliases — kimi #3158 port (git-style, alias-first) |
| `f7b2e4ef25` | feat(tui): refresh command catalog after /alias set — new quick commands appear in completion + palette immediately |
| `4f294b5727` | feat: quick commands surface in slash autocomplete (CLI + TUI) |

---

## 数据结构

```yaml
# config.yaml
quick_commands:
  ss: {type: alias, target: /sessions}    # alias 类型
  lg: {type: alias, target: /logs}        # alias 类型
  limits: {type: exec, command: echo ok}  # exec 类型
```

### quick_commands 支持两种类型

| 类型 | 说明 | 用途 |
|------|------|------|
| `alias` | 别名展开 | 将别名路由到另一个 slash 命令 |
| `exec` | 直接执行 | 执行 shell 命令（绕过 agent loop） |

---

## 核心逻辑分布

### 1. CLI 端 (`cli.py`)

#### 别名展开 — `process_command()` (L3231-3304)

```python
def process_command(self, command: str, _alias_depth: int = 0) -> bool:
    """
    _alias_depth: 递归守卫，防止无限循环
    - 用户别名精确展开一次
    - 第二次尝试展开时拒绝，防止 a → b → a 循环
    """
```

**展开流程：**
1. 解析命令基名 `_base_word`
2. 从 `config.yaml` 获取 `quick_commands`
3. 如果 `type == alias`，执行单跳展开
4. 追加用户参数到目标命令
5. 递归调用 `process_command`（`_alias_depth + 1`）

**关键代码段：**
```python
# cli.py:3289-3304
_qcs = self.config.get("quick_commands", {}) or {}
if _base_word in _qcs and isinstance(_qcs[_base_word], dict) and _qcs[_base_word].get("type") == "alias":
    _qc = _qcs[_base_word]
    if _cmd_def is not None:
        _cprint(f"  {_DIM}⚠ /{_base_word} shadows built-in /{canonical} (user alias wins){_RST}")
    _qc_target = (_qc.get("target") or "").strip()
    if _alias_depth >= 1:
        self._console_print("[bold red]Alias chain too deep — refusing to expand further[/]")
        return True
    # 递归展开
    return self.process_command(_aliased, _alias_depth=_alias_depth + 1)
```

#### `/alias` 命令处理 — `_handle_alias_command()` (L4140-4215)

```python
def _handle_alias_command(self, cmd_original: str) -> None:
    """
    /alias              → 列出所有别名
    /alias /<name> "<expansion>"  → 设置别名
    """
```

**子命令处理：**
1. 无参数 → 列出所有 `type: alias` 的配置
2. 有参数 → 解析名称和目标，写入 `config.yaml`
3. **立即生效**：同时更新内存中的 `self.config`

**参数验证：**
- 名称正则：`^[a-zA-Z0-9_:/.-]+$`
- 支持可选引号包裹目标
- 自动去除首尾引号
- 自动去除目标开头的 `/`

---

### 2. TUI Gateway 端 (`tui_gateway/methods_tools.py`)

#### 别名展开 — `command.dispatch` (L516-537)

```python
# 遍历别名链直到找到最终非 alias 目标
if qc.get("type") == "alias":
    target = (qc.get("target") or "").strip()
    seen = {name}
    while target:
        t_base = target.lstrip("/").split(maxsplit=1)[0]
        if t_base in seen:
            return _err(rid, 4018, "alias cycle detected: " + " → ".join(seen) + f" → {t_base}")
        seen.add(t_base)
        # 继续遍历...
    return _ok(rid, {"type": "alias", "target": target or name})
```

**TUI 展开特点：**
- **完整遍历别名链**，而非单跳
- 检测循环并报错
- 返回 `{type: 'alias', target: '/sessions'}` 给前端
- 前端收到后重新请求目标命令

#### `/alias` 命令处理 — `_handle_alias_dispatch()` (L1184-1269)

与 CLI 版本逻辑相同，但通过 JSON-RPC 返回。

```python
def _handle_alias_dispatch(rid: str, args: str, qcmds: dict) -> dict:
    """
    返回格式:
    - 成功: {"jsonrpc": "2.0", "id": rid, "result": {"type": "exec", "output": "..."}}
    - 失败: {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}
    """
```

---

### 3. 前端刷新 (`ui-tui/src/app/createSlashHandler.ts`)

#### Catalog 刷新 — `refreshCommandCatalog()` (L47-61)

```typescript
const refreshCommandCatalog = (): void => {
  gw.request<CommandsCatalogResponse>('commands.catalog', {})
    .then((catalog: CommandsCatalogResponse | null) => {
      if (stale() || !catalog?.pairs) return
      ctx.local.setCatalog({...})  // 更新本地 catalog 状态
    })
}
```

**刷新时机：**
- 在 `/alias set` 成功后调用
- 确保新别名立即出现在：
  - Slash 自动完成
  - 命令面板

---

## 命令注册集成 (`hermes_cli/commands.py`)

### 自动补全 (L2323-2356)

```python
# User-defined quick commands 在补全列表中出现
_qc_cfg = load_config_readonly().get("quick_commands") or {}
for qname, qc in sorted(_qc_cfg.items()):
    if _qtype == "alias":
        _qmeta = f"⚡ alias → {qc.get('target', '')}"
    elif _qtype == "exec":
        _qmeta = "⚡ exec: " + str(qc.get("command", ""))
    yield Completion(...)
```

**行为：**
- 用户别名在 CLI 和 TUI 的 slash 自动完成中显示
- 显示别名目标
- 跳过同名的内置命令（避免重复）

---

## 配置默认值

### `hermes_cli/config_defaults.py` (L2532-2533)

```python
# User-defined quick commands that bypass the agent loop (type: exec only)
"quick_commands": {},
```

---

## 安全考虑

1. **exec 类型不会覆盖别名展开路径**
   - `type: exec` 保持在备用路径，不会静默覆盖 `/stop` 等危险命令
   
2. **别名优先级规则**
   - 用户别名优先于内置命令
   - 但会显示警告：`⚠ /xxx shadows built-in /yyy (user alias wins)`

3. **参数隔离**
   - 别名展开时，用户参数追加到目标命令后
   - 格式：`/alias-name arg1 arg2` → `/target arg1 arg2`

---

## 测试覆盖

| 文件 | 测试内容 |
|------|----------|
| `tests/test_tui_gateway_server.py` | 别名在 slash.exec 中的路由 |
| `tests/test_tui_gateway_server.py` | Catalog 暴露 quick_commands |
| `tests/cli/test_quick_commands.py` | CLI 别名展开、别名链、循环检测 |
| `tests/gateway/test_slash_access_dispatch.py` | 非 admin 无法访问 exec 端点 |
| `tests/gateway/test_config.py` | quick_commands 配置合并 |

---

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 用户别名优先于内置 | git-style 惯例，用户控制权最大化 |
| 单跳展开（CLI）vs 完整遍历（TUI） | CLI 用深度守卫，TUI 在后端完整遍历 |
| 立即生效 | 与 kimi-code 行为一致，无重启负担 |
| 别名链支持 | `a → b → c` 合法，最终展开到 `c` |
| 循环检测 | 防止 `a → b → a` 无限递归 |

---

## 使用示例

```bash
# 设置别名
/hermes> /alias ss "/sessions"
  ✅ /ss → /sessions (immediate)

# 使用别名
/hermes> /ss
  → 展开为 /sessions，执行

# 列表查看
/hermes> /alias
  /ss → /sessions
  /lg → /logs

# 链式别名
/hermes> /alias dl "/devlogs"
/hermes> /alias dev "/dl"
/hermes> /dev
  → 展开为 /dl → /devlogs

# 冲突警告
/hermes> /alias sessions "/my-sessions"
  ⚠ /sessions shadows built-in /sessions (user alias wins)
```
