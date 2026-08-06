# Issue 9：interrupt_debug.log 明文落盘密钥（RedactingFormatter 被绕过）

> 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/75461
> 状态：🟢 干净候选（无认领、无评论、无关联 PR，2026-08-01 00:30 核查）
> 标签：type/security, comp/cli, area/auth, P2, sweeper:risk-security-boundary

## 一句话

用户往 Hermes 里粘贴 API key / bot token（配置平台时很常见）时，如果正好触发 interrupt，**原文会明文写进 `~/.hermes/interrupt_debug.log`，永远留在磁盘上**——因为这两处写入是裸 `open().write()`，绕过了全项目统一的 `RedactingFormatter`。

## Premise 验证（本地代码实锤）

全项目的日志体系（`hermes_logging.py`）所有 handler 都套了 `RedactingFormatter`，唯独 interrupt debug 的**两处**写入直接绕过：

```python
# cli.py:12000（中断触发时）
_dbg = _hermes_home / "interrupt_debug.log"
with open(_dbg, "a", encoding="utf-8") as _f:
    _f.write(f"{time.strftime('%H:%M:%S')} interrupt fired: msg={str(interrupt_msg)[:60]!r}, "
             f"children={len(self.agent._active_children)}, "
             f"parent._interrupt={self.agent._interrupt_requested}\n")

# cli.py:13160（消息进入中断队列时）
with open(_dbg, "a", encoding="utf-8") as _f:
    _f.write(f"{time.strftime('%H:%M:%S')} ENTER: queued interrupt msg={str(payload)[:60]!r}, "
             f"agent_running={self._agent_running}\n")
```

两处都直接 `str(interrupt_msg)` / `str(payload)`——用户刚粘贴的 token 原文就在里面。而且这个文件**从不清除**（issue 原文："stays there indefinitely"）。

## 为什么是"应该修"而不是"小事"

- **安全类 bug**：token 明文落盘 = 静态凭据泄露面。攻击者只要能读 `~/.hermes/`（或备份、日志收集器），就能拿到所有粘贴过的凭据。
- **P2 优先级**：不是 P3 边角料。
- **修复极小**：2 处写入 + 1 个现成函数，10 行内。

## 修复方案（★☆☆ 简单，可直接做）

`agent/redact.py:491` 有个为这种场景量身定做的函数：

```python
def redact_sensitive_text(text: str, *, force: bool = False, ...) -> str:
    """Set force=True for safety boundaries that must never return raw secrets
    regardless of the user's global logging redaction preference."""
```

**改动**（两处同构，各加一行）：

```python
from agent.redact import redact_sensitive_text  # 文件顶部已有类似 import 则复用

# cli.py:12000 处
_msg = redact_sensitive_text(str(interrupt_msg)[:60], force=True)
with open(_dbg, "a", encoding="utf-8") as _f:
    _f.write(f"... interrupt fired: msg={_msg!r}, ...")

# cli.py:13160 处
_msg = redact_sensitive_text(str(payload)[:60], force=True)
with open(_dbg, "a", encoding="utf-8") as _f:
    _f.write(f"... ENTER: queued interrupt msg={_msg!r}, ...")
```

`force=True` 关键：即使全局配置 `security.redact_secrets: false`，安全边界也绝不落原文（docstring 原话）。

**为什么要 `force=True` 而不是普通调用**：普通调用受用户全局开关控制——用户可能为了调试关掉脱敏，那这个 debug 文件又变回明文仓库。安全边界必须无条件脱敏。

## 测试思路

参考现有 `tests/agent/test_redact.py`（已有 300+ 行覆盖 `RedactingFormatter`）：

1. 单测 `redact_sensitive_text`：`"token: ghp_abcdef123456"` → 输出不含 `ghp_abcdef123456`（mask_secret 保留头尾，如 `ghp_S1...Pn2T`）
2. 集成（CLI 层）：mock 一个含 token 的 interrupt 消息 → 断言 `interrupt_debug.log` 内容已脱敏（用 `_isolate_hermes_home` fixture，不能写真实 `~/.hermes/`）
3. 回归：确认日志里时间戳、children 计数等调试信息格式不变

## 为什么不推荐同批的 #75416（Telegram DNS）

- 修复点在 adapter 重连状态机，涉及网络栈 + gateway 回复路径，本地无法端到端验证
- 需要设计决策（重连期间要不要缓存消息？），不是"改一行"的活
- 已确认 telegram_network.py 的 fallback transport 存在但问题在更高层，改动面模糊

## 撞车记录（本次核查 2026-08-01 00:30）

| issue | 结果 |
|---|---|
| #75399 cron show | ❌ 被标 duplicate（#18374），已有 PR #32772/#43031 |
| #75403 disk-cleanup | ❌ 已有 PR #75424（best fix）/#75464 |
| #75479 pricing api_key | ❌ 已有 PR #75510 |
| #75444 kanban decompose | ❌ 已有 PR #75490 |
| #75492 Google Chat OAuth | ❌ 关联 #27016 已有完整方案 |
| #75467 docker reap | ❌ 已有 PR #75483 |
| #75445 anthropic hooks | ❌ 已有 PR #75480 |
| #75468 desktop pin | ❌ main 已实现（f16b80362c） |
| **#75461 interrupt log** | ✅ **干净**（本报告） |
| #75416 telegram DNS | 🟡 干净但修复点模糊 |

教训再次验证：活跃仓库里 issue 从发布到被认领只有**几小时**，当天创建的 10 个候选 8 个已撞车。

## 复查记录（2026-08-01 03:05，tick#10 静默时段）

**#75461 仍干净**：state=open，assignees=无，comments=0，timeline 无 cross-referenced 事件。自 00:30 核查后 2.5 小时无变化 ✓

**本地源码复核（fork 当前 HEAD）**：
- `cli.py:11998-12006`（interrupt fired 写入）与 `cli.py:13158-13165`（ENTER 队列写入）——行号与记录一致，两处仍是裸 `open().write()`
- `agent/redact.py:491` 的 `redact_sensitive_text(text, *, force=False, code_file=False, file_read=False)` 在位，docstring 明确 `force=True` 用于"must never return raw secrets"的安全边界
- 现成先例：`cli.py:9068` 已用局部懒导入 `from agent.redact import redact_sensitive_text` —— 补丁沿用同一风格，不动顶部 import

## 补丁草稿（就绪，待用户拍板后应用）

**关键顺序决策：先脱敏、后截断**。原代码是 `str(payload)[:60]`（先截 60 字符）——如果密钥恰好横跨截断边界，截断会把 token 切半，前缀正则（`sk-`/`ghp_` 等）可能匹配不上，半截密钥照样落盘。改成先对**全文**脱敏、再截断展示，保证任何位置的密钥都被 mask。

```python
# ── 改动点 1：cli.py ~11998（interrupt fired 写入）──
                            # Debug: log to file (stdout may be devnull from redirect_stdout)
                            try:
                                from agent.redact import redact_sensitive_text   # ← 新增（局部懒导入，与 :9068 同风格）
                                _dbg = _hermes_home / "interrupt_debug.log"
                                with open(_dbg, "a", encoding="utf-8") as _f:
                                    _f.write(f"{time.strftime('%H:%M:%S')} interrupt fired: msg={redact_sensitive_text(str(interrupt_msg), force=True)[:60]!r}, "
                                             f"children={len(self.agent._active_children)}, "
                                             f"parent._interrupt={self.agent._interrupt_requested}\n")
                                    for _ci, _ch in enumerate(self.agent._active_children):
                                        _f.write(f"  child[{_ci}]._interrupt={_ch._interrupt_requested}\n")

# ── 改动点 2：cli.py ~13158（ENTER 队列写入）──
                        # Debug: log to file when message enters interrupt queue
                        try:
                            from agent.redact import redact_sensitive_text   # ← 新增
                            _dbg = _hermes_home / "interrupt_debug.log"
                            with open(_dbg, "a", encoding="utf-8") as _f:
                                _f.write(f"{time.strftime('%H:%M:%S')} ENTER: queued interrupt msg={redact_sensitive_text(str(payload), force=True)[:60]!r}, "
                                         f"agent_running={self._agent_running}\n")
                        except Exception:
                            pass
```

改动量：+2 行 import、2 处表达式替换，无其他行为变化。`child[i]._interrupt` 那行只写布尔值，不用动。

**测试**（沿用报告方案）：
1. 单测：`redact_sensitive_text("token: ghp_abcdef123456", force=True)` 不含 `ghp_abcdef123456`
2. 集成：mock 含 token 的 interrupt 消息 → 断言 `interrupt_debug.log` 内容已脱敏（`_isolate_hermes_home` fixture，不写真实 `~/.hermes/`）
3. 回归：时间戳/children 计数格式不变

---

🔗 官方 Issue：https://github.com/NousResearch/hermes-agent/issues/75461
