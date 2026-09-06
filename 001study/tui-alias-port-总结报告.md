# 本地移植总结报告：Hermes quick_commands alias（kimi #3158 移植）

> 分支：`tui-alias`（hermes-agent-plus）
> 提交：3 个（见下），相对 `upstream/main` 共 8 文件，+700 / −16
> 蓝本：kimi-code `bc71ab7cf`（local-upstream 分支，14 文件 +654/−1）——对应文档见 `kimi-code-study/002study/local-upstream-aliases-总结报告.md`
> 定位：**本地 fork 自用功能移植**，非上游合入；沿用 kimi 版"个人 fork 实验"路线（story-5《开源贡献正在变难》讨论过 Nous vs Moonshot 北极星差异）
> 日期：2026-09-02

---

## 零、为什么做这次移植（背景链）

1. **2026-08-20**：用户给 kimi-code 提 issue #3158（git 风格别名），后落成 local-upstream 提交 `bc71ab7cf`
2. **2026-08-22**：用户想把同一功能给 Hermes。深度分析发现 **Hermes 已有 `quick_commands` alias 配置，但 TUI 端有断点**——`slash.exec` 不认 quick_commands，`/ss` 被当未知命令返回纯文本，弹不出 sessions 选择器（bug 根因：TUI 前端默认执行路径 `slash.exec` 与 quick_commands 的识别位置 `command.dispatch` 没对齐）
3. **2026-08-23**：源码调研确认 Hermes 原生已有 quick_commands（config.yaml，`type: alias`/`type: exec`），CLI/gateway/desktop 都认识；真正的增量缺口 = `/alias` 配置命令 + TUI 断点 + 补全 + 优先级。调研文档：`002study/hermes-alias-migration-research.md`
4. **2026-09-02**：用户拍板按 kimi 语义移植（**用户别名优先 + 遮蔽警告**），分支名 `tui-alias`

## 一、基线（这个改动是在什么基础上做的）

- **分支起点**：`upstream/main` 本地引用 `c30ac90a92`（2026-08-28，feat(compaction) #97073）
- **与运行版的关系**：运行版 `/usr/local/lib/hermes-agent` = `ad4adbbfe`（08-28 05:12），比 base **多 1 个 commit**（install 门控提示修复，与本次改动无关）。即：tui-alias 比运行版多 3 个功能提交、少 1 个无关提交——**cherry-pick 到运行版预期干净**（详见"待办"）
- **与真正上游的关系**：本地 upstream 引用停留在 8-28（期间 GitHub fetch 429 限流未拉到新提交），8-28 之后上游是否有新改动未知

## 二、三个提交一览

```
tui-alias（= upstream/main c30ac90a92 + 3 commits，8 files +700/−16）
│
├── 4f294b5727  feat: quick commands 进自动补全（CLI+TUI）      [+35, 1 file]
│               ← 用户反馈："TUI 里没看到 /ss"（输入补全下拉无提示）
│
├── f7b2e4ef25  feat(tui): /alias 设置后刷新命令面板           [+27/−1, 1 file]
│               ← 用户反馈："加入 /ss 没立马显示在可选命令"
│
└── fdb7aa441b  feat: alias 移植主提交（三端 + 测试）           [+638/−15, 7 files]
                kimi 六块能力落 Hermes 的主工作
```

## 三、修改文件一览（树形图）

```
tui-alias  (+700 / −16, 8 files, 3 commits)
│
├── CLI 端
│   └── cli.py                                [+124]  主提交
│       ├── process_command 加 _alias_depth 参数（单跳防环）
│       ├── canonical 分发前插"别名优先"块（kimi 语义：用户别名遮蔽内置时警告）
│       ├── else 分支的 alias 处理改为死代码诊断（展开已提前）
│       └── 新增 _handle_alias_command（/alias list/set，写 config + 内存同步）
│
├── Gateway 端（飞书/消息平台）
│   └── gateway/run.py                        [+86]   主提交
│       ├── alias 展开条件从"仅未知命令"改为"无条件优先"
│       │   （原代码 `_cmd_def is None` 才查；exec 类型仍保持内置优先，防 shell 遮蔽 /stop）
│       └── 新增 _handle_alias_command handler + canonical 分发分支
│
├── TUI 后端（tui_gateway）
│   ├── methods_tools.py                      [+133]  主提交
│   │   ├── slash.exec 补 quick_commands 路由   ← 8-22 断点根修（~8 行）
│   │   ├── command.dispatch 的 alias 分支改"链展开到底 + visited 环检测"
│   │   └── 新增 _handle_alias_dispatch（TUI/desktop 共用 /alias 命令）
│   └── server.py                              [+6]    主提交
│       └── 把 _handle_alias_dispatch 挂进 server 命名空间
│           （handler rebind 机制：register() 后 __globals__ 是 server.py，
│            普通 def 在 methods_tools 里不可达——同 _mcp_* 辅助函数模式）
│
├── TUI 前端（ui-tui，TypeScript）
│   └── src/app/createSlashHandler.ts          [+27/−1] 前端刷新提交
│       ├── 新增 refreshCommandCatalog()（复用 /reload-skills 的 setCatalog 段）
│       └── handleDispatch 收到 /alias 的 exec 结果后触发刷新
│           （对应 kimi 的 refreshAliases()：别名立即进补全 + 面板）
│
├── 统一注册表 + 补全（hermes_cli）
│   └── commands.py                            [+2] 主提交  + [+35] 补全提交
│       ├── COMMAND_REGISTRY 加 CommandDef("alias", …, aliases=("aliases",))
│       │   （统一注册表 = CLI/gateway/TUI/desktop 自动可见）
│       └── SlashCommandCompleter.get_completions 加第 5 数据源：quick_commands
│           （CLI prompt_toolkit 和 TUI complete.slash RPC 共用此 completer，
│             一处修复两端生效；同内置名去重；meta 显示 ⚡ alias → target）
│
└── 测试
    ├── tests/cli/test_quick_commands.py       [+155] 主提交（+9 用例）
    │   └── CLI/gateway：别名优先遮蔽、防环、参数拼接、/alias list/set、遮蔽警告
    └── tests/test_tui_gateway_server.py       [+147] 主提交（+6 用例）
        └── slash.exec 路由、alias 链展开、环检测、/alias list/set、exec 路由
```

## 四、kimi 六块能力 → Hermes 落地对照

| kimi 蓝本能力 | Hermes 落地 | 差异说明 |
|---|---|---|
| config 层 `[aliases]` 段 | **复用原生 `quick_commands`**（config.yaml，`{type: alias, target:}`） | 不新开段：Hermes 已有多端支持，零迁移、零侵入 |
| TUI `/alias` 命令 | CLI/TUI/gateway 三端各一 handler（共享 COMMAND_REGISTRY 注册） | kimi 只有 TUI；Hermes 因多端架构写了三份薄 handler |
| 解析层单跳重写（resolve.ts） | TUI：command.dispatch 链展开到底 + visited；CLI：`_alias_depth` 单跳；gateway：事件文本改写天然单跳 | kimi 重写点在最上游；Hermes 各端在各自命令入口展开 |
| 防环（aliasMap: undefined） | CLI 深度 1 层即拒；TUI visited-set 环直接报错；gateway 天然单跳 | Hermes TUI 比 kimi 更严（环报错而非 fall through） |
| 优先级（用户别名优先 + 遮蔽警告） | 三端 alias 展开提到内置分发**前**；/alias set 时检测遮蔽并警告 | 只对 alias 类型优先；**exec 保持内置优先**（防 shell 遮蔽 /stop 的安全面） |
| 零侵入 | 无 quick_commands 配置时行为不变 | ✅ 天然满足（复用原生配置） |
| （kimi 另有）别名进 autocomplete | SlashCommandCompleter 加 quick_commands 源（CLI+TUI 共用） | kimi 是 aliasCommands 进 setupAutocomplete；Hermes 因共用 completer 一处改两端 |

## 五、测试与验证

- 新增用例 **15 个**（CLI/gateway 9 + TUI 6），全绿
- 回归：quick_commands 相关 + TUI gateway 全量 + slash 补全相关 = **700+ passed 零破坏**
- 手动端到端验证：
  - `complete.slash` 输入 `/ss` → 返回 `ss | ⚡ alias → /sessions` ✅
  - 运行版旧代码实测 `/ss 42` → `_handle_sessions_command('/sessions 42')`（对照确认旧版 CLI 本可展开，问题只在 TUI/补全）

## 六、待办 / 风险

1. **运行版同步（未做）**：cherry-pick 3 提交到 `/usr/local/lib/hermes-agent` + 重启 gateway 后，飞书 bot 才有 `/alias` 命令与补全。base 差 1 个无关 commit，预期干净
2. **Desktop 端 catalog 缓存（未确认）**：`apps/desktop/src/lib/slash-completion-cache.ts` 有 `cachedSlashCompletion('catalog')` 缓存，`/alias` 后 desktop 是否刷新待查（ui-tui 已修）
3. **`hermes update` 冲突风险**：改动触及上游高频文件（cli.py / methods_tools.py / gateway/run.py），若 cherry-pick 到运行版 main，每次 `git pull` 上游都可能撞同一批文件需手动解冲突（kimi story-5 讨论过的 fork 自用成本）
4. **上游跟踪**：本地 upstream 引用停在 8-28，真实上游可能有新提交（fetch 429 未拉到）

## 七、证据链接

- kimi 蓝本提交：`bc71ab7cf`（kimi-code-study local-upstream 分支）
- kimi 版总结报告：`kimi-code-study/002study/local-upstream-aliases-总结报告.md`
- Hermes 调研文档：`002study/hermes-alias-migration-research.md`（2026-08-23）
- 本分支三个提交：`fdb7aa441b`、`f7b2e4ef25`、`4f294b5727`
