# 走读卡 3.1：cli.py 无痛阅读地图 — 298 个函数三分类速查

> 教学读代码序列 · 3.1 号（cli.py 专项）· 2026-08-05
> 方法论来源：`painless-code-reading` skill（签名分类法）
> 数据来源：对 cli.py 全部 298 个函数签名做程序化扫描
> **本卡作用：给你一张地图——哪些函数看名字就懂、哪些是空壳、哪些要读实现**

---

## 一、先给结论：298 个函数 = 117 + 24 + 157

```
① 纯函数（看签名就懂，跳过实现）  117 个 ≈ 39%
② 包装器（签名是空壳，找真身）     24 个 ≈  8%
③ 副作用（签名不解释，按需读）    157 个 ≈ 53%
```

**阅读策略一句话：跳过 ①，追源头 ②，按需点开 ③。真正需要精读的不到 20 个。**

---

## 二、① 纯函数（117 个）— 看签名就懂，直接跳过

特征：参数有类型标注 + 返回值有类型标注 + 名字直白。**签名本身就是文档**。

```python
cli.py:196   _strip_reasoning_tags(text: str) -> str        # 文本处理
cli.py:268   _assistant_content_as_text(content: Any) -> str
cli.py:291   _load_prefill_messages(file_path: str) -> List[Dict]
cli.py:320   _resolve_prefill_messages_file(config) -> str
cli.py:339   _parse_reasoning_config(effort) -> dict | None
cli.py:362   load_cli_config() -> Dict[str, Any]
cli.py:1337  _normalize_git_bash_path(p: Optional[str]) -> Optional[str]
cli.py:1366  _git_repo_root() -> Optional[str]              # git 工具
cli.py:1387  _path_is_within_root(path, root) -> bool
cli.py:1471  _setup_worktree(repo_root=None, sync_base=True) -> Optional[Dict]
cli.py:1639  _worktree_has_unpushed_commits(path, timeout=10) -> bool
cli.py:1670  _worktree_is_dirty(path, timeout=10) -> bool
cli.py:2091  _hex_to_ansi(hex_color: str, *, bold=False) -> str   # 颜色/皮肤
cli.py:2132  _luminance_from_hex(hex_str) -> float | None
cli.py:2219  _detect_light_mode() -> bool
cli.py:2445  _strip_markdown_syntax(text: str) -> str       # markdown 渲染
cli.py:2826  _split_path_input(raw: str) -> tuple[str, str]
cli.py:2869  _resolve_attachment_path(raw_path) -> Path | None
cli.py:2933  _detect_file_drop(user_input) -> dict | None
cli.py:3005  _format_image_attachment_badges(...) -> str
cli.py:3038  _should_auto_attach_clipboard_image_on_paste(text) -> bool
```

**结论：这批函数 95% 是边角料**（颜色、markdown、git worktree、图片附件），
跟 agent 核心无关。名字+签名已经说明一切，永远不需要打开它们。

---

## 三、② 包装器（24 个）— 签名是空壳，真身藏在别的模块

特征：`(*args, **kwargs)` 把参数全吞了。**这是懒加载**——启动时不 import 重模块，
等真调用才加载。你要读的是它转发的"真身"。

```python
cli.py:95    CanonicalUsage(*args, **kwargs)      # 真身在 hermes_cli.*
cli.py:101   estimate_usage_cost(*args, **kwargs)
cli.py:107   format_duration_compact(*args, **kwargs)
cli.py:122   format_token_count_compact(*args, **kwargs)
cli.py:146   is_table_divider(*args, **kwargs)    # markdown 表格工具
cli.py:152   looks_like_table_row(*args, **kwargs)
cli.py:158   realign_markdown_tables(*args, **kwargs)

cli.py:841   AIAgent(*args, **kwargs)             # ★ 真身 run_agent.py 的 AIAgent
cli.py:847   get_tool_definitions(*args, **kwargs) # ★ 真身 tools/tool_definitions
cli.py:855   get_toolset_for_tool(*args, **kwargs)
cli.py:865   get_all_toolsets(*args, **kwargs)
cli.py:871   get_toolset_info(*args, **kwargs)
cli.py:877   validate_toolset(*args, **kwargs)

cli.py:890   get_job(*args, **kwargs)             # ★ cron 相关，真身 agent/cron
cli.py:899   _cleanup_all_terminals(*args, **kwargs)  # 真身 tools/terminal
cli.py:905   set_sudo_password_callback(*args, **kwargs)  # 真身 tools/sudo
cli.py:911   set_approval_callback(*args, **kwargs)
cli.py:917   set_secret_capture_callback(*args, **kwargs)

cli.py:3596  build_skill_invocation_message(*args, **kwargs)  # ★ skill 相关
cli.py:3602  build_preloaded_skills_prompt(*args, **kwargs)
cli.py:3617  build_bundle_invocation_message(*args, **kwargs)
```

**怎么找真身**（识别技巧）：

```bash
grep -A3 "^def AIAgent" cli.py
# 会看到：from run_agent import AIAgent as _impl → return _impl(*args, **kwargs)
```

**结论：这 24 个包装器 = cli.py 的"贸易口岸"**——它自己不实现，全是转发。
带 ★ 的 4 个（AIAgent / get_tool_definitions / get_job / skill 系列）是通往
agent 核心的门，值得去真身那边读；其余 20 个是边角转发。

---

## 四、③ 副作用函数（157 个）— 签名不解释行为，按需点开

特征：`-> None` 或没有返回值标注。**数据不通过返回值出来**，靠改全局状态、
打印、注册回调干活。签名回答不了"它干了啥"，必须读实现。

```python
cli.py:883   _sync_process_session_id(session_id)       # 同步到哪？读实现
cli.py:996   _arm_exit_watchdog(timeout_s=None)         # 退出看门狗
cli.py:1105  _run_cleanup(*, notify_session_finalize=True)  # 清理钩子
cli.py:1285  _reset_terminal_input_modes_on_exit()      # 终端模式
cli.py:1894  _prune_stale_worktrees(repo_root, max_age_hours=24)
cli.py:2005  _prune_orphaned_branches(repo_root)
cli.py:2515  _render_final_assistant_content(text, mode="render")  # ★ 渲染回答
cli.py:2567  _configure_output_history(enabled, max_lines=200)
cli.py:2639  _cprint(text)                              # ★ 打印到控制台
cli.py:2744  _prepend_note_to_message(message, note)    # ★ 给消息加前缀
cli.py:3200  _bind_prompt_submit_keys(kb, handler)      # prompt_toolkit 按键
cli.py:4205  _release_active_session(self)              # 会话锁
...（共 157 个，绝大多数是终端/渲染/清理/回调注册）
```

**阅读策略**：这批函数**不需要主动读**。什么时候读？当你顺着主调用链走到它、
需要理解某个行为时再点开 5~10 行。其中带 ★ 的 4 个（_cprint / _render /
_prepend_note / _release_active_session）与主链相关，其余基本可终身不碰。

---

## 五、主调用链（建议精读的 6 个函数）

这才是 cli.py 里"值得你花时间"的全部内容：

```
cli.py:15384  main()                     ← 入口：参数→对象
cli.py:12749  HermesCLI.run()            ← 交互主循环（双队列设计）
cli.py:12991  handle_enter()             ← Enter 键按状态分发
cli.py:11590  HermesCLI.chat()           ← 每轮对话的准备工作
cli.py:11900  run_conversation() 调用点   ← 离开 CLI，进入核心引擎
（真身）agent/conversation_loop.py:588  run_conversation() ← 引擎本体
```

**298 个函数，你要读的就这 6 个 + 少量按需点开。其余 292 个：117 个跳过、
20 个转发边角、155 个副作用边角。**

---

## 六、动手实验（2 分钟）

```bash
cd /root/projects/hermes-agent-plus

# 1. 验证分类数据（自己跑一遍）
python3 -c "
import re
src = open('cli.py', encoding='utf-8').read()
lines = src.split('\n')
funcs = []
for i, line in enumerate(lines, 1):
    m = re.match(r'^(?:def |    def )(\w+)\((.*?)\)(?: -> (.*?))?:', line)
    if m:
        funcs.append((i, m.group(1), m.group(2).strip(), m.group(3).strip() if m.group(3) else ''))
wrapper = [f for f in funcs if '*args' in f[2] and '**kwargs' in f[2]]
side = [f for f in funcs if f not in wrapper and (f[3] == 'None' or f[3] == '')]
pure = [f for f in funcs if f not in wrapper and f not in side]
print(f'纯函数 {len(pure)} / 包装器 {len(wrapper)} / 副作用 {len(side)} / 总计 {len(funcs)}')
"

# 2. 验证包装器找真身的方法
grep -A3 "^def AIAgent" cli.py

# 3. 看主链入口
grep -n "def main\|def run\|def chat" cli.py | head -5
```

## 七、思考题（3 道）

1. **复述题**：三类函数各有什么特征？哪一类"看签名就能判断意图"？哪一类必须读实现？
2. **预测题**：`build_preloaded_skills_prompt(*args, **kwargs)` 这个包装器（cli.py:3602），
   它的真身应该在哪个模块？为什么它要懒加载？（提示：跟走读卡 1/2 的 skill 链路怎么串上？）
3. **追问题**：副作用函数占了 53%——这是"坏味道"吗？如果全改成纯函数会怎样？
   （提示：想想 `_cprint` 改成返回字符串后，调用方要改多少处？为什么 CLI 这种 UI 层
   天然多副作用函数？）

---

下一条预告：按计划回到主链——tool/toolset 系统的加载与注册（`_execute_tool_calls` 内部）。
本卡的方法论可复用到 run_agent.py（6682 行）等其他大文件。
