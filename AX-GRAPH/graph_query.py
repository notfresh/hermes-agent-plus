#!/usr/bin/env python3
"""X-GRAPH 查询工具：查看某节点的第一层外围（直接邻居 + 关系）

用法:
    python3 graph_query.py <节点id或关键词> [-l 过滤]
    python3 graph_query.py                    # 无参数：列出可查节点

-l/--layer 过滤（可省略，缺省=全部）:
    数字      只查对应文件层，如 -l 1 只看 Layer-1-Graph.toml 的关系
    架构层名  只看该架构层节点，如 -l core / -l interface / -l application

特性:
    - 模糊匹配：精确 → 包含 → 近似
    - 缺参自动提示，不报错
    - 输出节点信息 + 出边(→谁) + 入边(谁→)
"""
import sys
import re
import tomllib
import difflib
import argparse
from pathlib import Path

BASE = Path(__file__).parent
ACTIVE_FILE = BASE / ".active-base"
ARCH_LAYERS = {"core", "interface", "capability", "application", "entry", "infra"}
VALID_KINDS = {"module", "file", "cluster", "subpackage", "feature", "function", "constants"}
VALID_RELS = {"CONTAINS", "DEPENDS_ON", "REALIZED_BY", "CALLS"}


# ── base 管理（多库体系，类似 select database）──

def get_active_base() -> str:
    """当前默认 base（.active-base 记录，缺省 base-dir-hermes_agent）。"""
    try:
        name = ACTIVE_FILE.read_text(encoding="utf-8").strip()
        if name and (BASE / name).is_dir():
            return name
    except Exception:
        pass
    return "base-dir-hermes_agent"


def set_active_base(name: str) -> None:
    """切换默认 base（持久化到 .active-base）。"""
    ACTIVE_FILE.write_text(name, encoding="utf-8")


def base_dir(name: str = None) -> Path:
    """指定 base 的目录（缺省=当前默认）。"""
    return BASE / (name or get_active_base())


def get_base_meta(name: str = None) -> dict:
    """读 base.toml 元信息（type/source/repo/desc），缺失返回默认。"""
    bd = base_dir(name)
    meta = {"type": "dir", "source": "", "repo": ""}
    meta_file = bd / "base.toml"
    if meta_file.exists():
        try:
            with open(meta_file, "rb") as f:
                m = tomllib.load(f).get("base", {})
            meta.update(m)
        except Exception:
            pass
    if not meta.get("repo"):
        meta["repo"] = str(Path(__file__).parent.parent)
    return meta


def get_repo(name: str = None) -> Path:
    """当前 base 的仓库根（节点 path 相对它解析）。"""
    return Path(get_base_meta(name).get("repo", str(Path(__file__).parent.parent)))


def list_bases() -> list:
    """列出全部 base（base-* 目录 + 元信息）。"""
    out = []
    for d in sorted(BASE.glob("base-*")):
        if d.is_dir():
            meta = get_base_meta(d.name)
            out.append((d.name, meta))
    return out
def ppath(node):
    """path 输出统一 ./ 前缀（VSCode Ctrl+点击跳转友好）"""
    p = node.get("path") if node else None
    return f"./{p}" if p else "?"


def ploc(path, at):
    """调用点位置输出：./文件:行号"""
    if not path or not at or at == "?":
        return "?"
    return f"./{path.split(':')[0]}:{at}"



def load(layer_num=None):
    """合并加载当前 base 目录所有 Layer-*-Graph.toml；layer_num 指定时只加载对应文件。"""
    data = {"nodes": [], "edges": []}
    bd = base_dir()
    files = sorted(bd.glob("Layer-*.toml"))
    if layer_num is not None:
        files = [p for p in files if p.name.startswith(f"Layer-{layer_num}-Graph")]
    for p in files:
        with open(p, "rb") as f:
            d = tomllib.load(f)
        for n in d["nodes"]:
            n["source"] = p.name
        for e in d["edges"]:
            e["source"] = p.name
        data["nodes"].extend(d["nodes"])
        data["edges"].extend(d["edges"])
    return data


def fuzzy_find(nodes, query):
    """模糊匹配：%通配（MySQL LIKE）→ 精确 → 包含 → 近似"""
    ids = [n["id"] for n in nodes]
    if "%" in query:
        # MySQL LIKE 风格：% = 任意多个字符（含 0 个）
        rx = re.compile("^" + ".*".join(re.escape(p) for p in query.split("%")) + "$")
        hits = [i for i in ids if rx.match(i)]
        if hits:
            return hits
        # 也匹配 path 字段
        return [n["id"] for n in nodes if n.get("path") and rx.match(n["path"])]
    if query in ids:
        return [query]
    matches = [i for i in ids if query in i]
    if matches:
        return matches
    return difflib.get_close_matches(query, ids, n=5, cutoff=0.4)


def explain_edge(e, nodes):
    """把一条边翻译成中文解释"""
    f = nodes.get(e["from"], {})
    t = nodes.get(e["to"], {})
    rel = e["rel"]
    if rel == "CONTAINS":
        return f"{e['from']} 包含 {e['to']} —— {e['to']} 属于 {e['from']}（内聚归属，'它属于谁'）"
    if rel == "DEPENDS_ON":
        w = e.get("weight", "?")
        if f.get("kind") == "module" and t.get("kind") == "module":
            return f"{e['from']} 依赖 {e['to']} —— 模块级耦合，代码里有 {w} 处 import（'它用到谁'）"
        return f"{e['from']} 用到 {e['to']} —— {w} 处 import"
    if rel == "REALIZED_BY":
        return f"{e['from']} 由 {e['to']} 实现 —— 想研究这个功能，从这里读起"
    if rel == "CALLS":
        return f"{e['from']} 调用 {e['to']} —— 执行顺序：先执行前者，再进后者"
    return f"{e['from']} --{rel}--> {e['to']}"


def show(nid, data, arch=None, explain=False):
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    node = nodes.get(nid)
    if not node:
        print(f"节点不存在: {nid}")
        return

    print(f"\n=== {nid} ===")
    print(f"  kind={node.get('kind')}  path= {ppath(node)}  layer={node.get('layer', '-')}  [{node.get('source', '')}]")
    if node.get("desc"):
        print(f"  desc: {node['desc']}")

    out = [e for e in edges if e["from"] == nid and (arch is None or nodes.get(e["to"], {}).get("layer") == arch)]
    inn = [e for e in edges if e["to"] == nid and (arch is None or nodes.get(e["from"], {}).get("layer") == arch)]

    if arch:
        print(f"\n-- 出边 {len(out)} 条（{nid} → 谁，仅{arch}层）--")
    else:
        print(f"\n-- 出边 {len(out)} 条（{nid} → 谁）--")
    for e in sorted(out, key=lambda e: (e["rel"], e["to"])):
        w = f"  weight={e['weight']}" if e.get("weight") else ""
        note = f"  [{e['note']}]" if e.get("note") else ""
        d = nodes.get(e["to"], {}).get("desc", "")
        print(f"  [{e['rel']}] → {e['to']}{w}  {d}{note}")

    if arch:
        print(f"\n-- 入边 {len(inn)} 条（谁 → {nid}，仅{arch}层）--")
    else:
        print(f"\n-- 入边 {len(inn)} 条（谁 → {nid}）--")
    for e in sorted(inn, key=lambda e: (e["rel"], e["from"])):
        w = f"  weight={e['weight']}" if e.get("weight") else ""
        note = f"  [{e['note']}]" if e.get("note") else ""
        d = nodes.get(e["from"], {}).get("desc", "")
        print(f"  [{e['rel']}] {e['from']} →{w}  {d}{note}")

    if explain:
        print("\n📖 关系解读（人话版）")
        if out:
            print("  出边（它 → 谁，它依赖/包含谁）：")
            for e in sorted(out, key=lambda e: (e["rel"], e["to"])):
                print(f"    · {explain_edge(e, nodes)}")
        if inn:
            print("  入边（谁 → 它，谁依赖/包含/实现它）：")
            for e in sorted(inn, key=lambda e: (e["rel"], e["from"])):
                print(f"    · {explain_edge(e, nodes)}")


def show_callchain(nid, data):
    """从入口节点沿 CALLS 边展开调用链（V2：树形 + 职责摘要 + 调用点行号）"""
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    if nid not in nodes:
        print(f"节点不存在: {nid}")
        return
    adj = {}
    call_edge = {}  # (from,to) -> edge
    for e in edges:
        if e["rel"] == "CALLS":
            adj.setdefault(e["from"], []).append(e["to"])
            call_edge[(e["from"], e["to"])] = e

    root = nodes[nid]
    print(f"\n=== 调用链展开：{nid} ===")
    print(f"  {nid}  path= {ppath(root)}")
    print(f"      {root.get('desc', '')}")
    visited = {nid}

    def dfs(node, parent, prefix, is_last, depth):
        if depth > 8:
            print(f"{prefix}{'└── ' if is_last else '├── '}…（超过 8 层，截断）")
            return
        n = nodes.get(node, {})
        branch = "└── " if is_last else "├── "
        at = call_edge.get((parent, node), {}).get("at_line", "?") if parent else "-"
        at_loc = ploc(nodes.get(parent, {}).get("path"), at) if parent else "-"
        print(f"{prefix}{branch}{node}  path= {ppath(n)}  ← 调用点: {at_loc}")
        print(f"{prefix}{'    ' if is_last else '│   '}    {n.get('desc', '')}")
        nxt = prefix + ("    " if is_last else "│   ")
        children = [c for c in adj.get(node, []) if c not in visited]
        if not children:
            return
        visited.add(node)
        for i, c in enumerate(children):
            dfs(c, node, nxt, i == len(children) - 1, depth + 1)

    children = adj.get(nid, [])
    if not children:
        print("  （无 CALLS 出边——没有调用其他图内函数）")
        return
    for i, c in enumerate(children):
        dfs(c, nid, "  ", i == len(children) - 1, 1)


def show_callers(nid, data):
    """反向调用链：谁在调用我（沿 CALLS 入边向上展开）"""
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    if nid not in nodes:
        print(f"节点不存在: {nid}")
        return
    rev_adj = {}
    call_edge = {}  # (to, from) -> edge（反向记录）
    for e in edges:
        if e["rel"] == "CALLS":
            rev_adj.setdefault(e["to"], []).append(e["from"])
            call_edge[(e["to"], e["from"])] = e

    root = nodes[nid]
    print(f"\n=== 反向调用链（谁在调用我）：{nid} ===")
    print(f"  {nid}  path= {ppath(root)}")
    print(f"      {root.get('desc', '')}")
    visited = {nid}

    def dfs(node, child, prefix, is_last, depth):
        if depth > 8:
            print(f"{prefix}{'└── ' if is_last else '├── '}…（超过 8 层，截断）")
            return
        n = nodes.get(node, {})
        branch = "└── " if is_last else "├── "
        e = call_edge.get((child, node), {})  # key=(to,from)，child 是被调用者(to)，node 是调用者(from)
        at = e.get("at_line", "?")
        at_loc = ploc(n.get("path"), at)
        print(f"{prefix}{branch}{node}  path= {ppath(n)}  ← 调用点: {at_loc}")
        print(f"{prefix}{'    ' if is_last else '│   '}    {n.get('desc', '')}")
        nxt = prefix + ("    " if is_last else "│   ")
        parents = [p for p in rev_adj.get(node, []) if p not in visited]
        if not parents:
            return
        visited.add(node)
        for i, p in enumerate(parents):
            dfs(p, node, nxt, i == len(parents) - 1, depth + 1)

    callers = rev_adj.get(nid, [])
    if not callers:
        print("  （无人调用它——没有 CALLS 入边）")
        return
    for i, c in enumerate(callers):
        dfs(c, nid, "  ", i == len(callers) - 1, 1)


from collections import Counter


def details_file() -> Path:
    """当前 base 的 NodeDetails.toml。"""
    return base_dir() / "NodeDetails.toml"


def load_details():
    """加载当前 base 的 NodeDetails.toml（KV：节点id → 详细介绍文本）。不存在返回 {}。"""
    df = details_file()
    if not df.exists():
        return {}
    try:
        with open(df, "rb") as f:
            return tomllib.load(f).get("details", {})
    except Exception:
        return {}


def save_details(details):
    """写当前 base 的 NodeDetails.toml（多行字符串字面量，KV 形式）。"""
    lines = [
        "# 节点详细介绍（KV：节点id → 多行 markdown 读码笔记）",
        "# 由 graph_query.py -b 维护（vim 编辑），勿手改格式",
        "",
        "[details]",
    ]
    for k in sorted(details):
        v = details[k].replace('"""', '\\"""')
        lines.append(f'"{k}" = """')
        lines.append(v)
        lines.append('"""')
        lines.append("")
    details_file().write_text("\n".join(lines), encoding="utf-8")


def build_detail(nid, text=None):
    """-b 构建节点详细介绍：--text 直写；缺省打开 $EDITOR（缺省 vim）编辑临时文件。
    预填旧内容；清空保存=删除该详情。返回退出码。"""
    nodes = load()["nodes"]
    matches = fuzzy_find(nodes, nid)
    if not matches:
        print(f"未找到匹配: {nid}")
        return 1
    target = matches[0]
    if len(matches) > 1:
        print(f"匹配 {len(matches)} 个，编辑第一个: {target}（其余: {', '.join(matches[1:5])}）")
    details = load_details()
    old = details.get(target, "")

    if text is not None:
        if text.strip():
            details[target] = text.strip()
            print(f"✓ 已写入 {target} 的详细介绍（{len(text.strip())} 字符）")
        else:
            details.pop(target, None)
            print(f"已删除 {target} 的详细介绍")
        save_details(details)
        return 0

    import os
    import subprocess
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix=".md", prefix="xgraph-detail-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(old)
    editor = os.environ.get("EDITOR", "vim")
    print(f"打开 {editor} 编辑 [{target}] 的详细介绍（保存退出后自动写入；清空保存=删除）")
    try:
        rc = subprocess.call([editor, tmp])
    except FileNotFoundError:
        os.unlink(tmp)
        print(f"找不到编辑器 {editor}（设置 EDITOR 环境变量，或改用 --text 直写）")
        return 1
    if rc != 0:
        os.unlink(tmp)
        print(f"编辑器异常退出（rc={rc}），未保存")
        return 1
    with open(tmp, encoding="utf-8") as f:
        new = f.read().strip()
    os.unlink(tmp)
    if not new:
        details.pop(target, None)
        print(f"已删除 {target} 的详细介绍")
    else:
        details[target] = new
        print(f"✓ 已写入 {target} 的详细介绍（{len(new)} 字符）")
    save_details(details)
    return 0


def show_detail(nid, data):
    """-d 显示节点详细介绍（show 模式末尾调用）。"""
    details = load_details()
    det = details.get(nid)
    print()
    if det:
        print(f"-- 📖 详细介绍（NodeDetails.toml）--")
        print(det)
    else:
        print(f"（{nid} 暂无详细介绍，可执行 -b {nid} 添加）")


def show_feature_callgraph(nid, data):
    """feature 节点的内部调用图：实现函数之间的 CALLS 关系 + 入口/中间/叶子角色"""
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    funcs = [
        e["to"] for e in edges
        if e["from"] == nid and e["rel"] == "REALIZED_BY" and nodes.get(e["to"], {}).get("kind") == "function"
    ]
    if not funcs:
        print("  （该节点没有 REALIZED_BY 实现函数）")
        return
    fset = set(funcs)
    calls = [e for e in edges if e["rel"] == "CALLS" and e["from"] in fset and e["to"] in fset]
    indeg = Counter(e["to"] for e in calls)
    outdeg = Counter(e["from"] for e in calls)

    print(f"\n=== {nid} 内部调用图（{len(funcs)} 个实现函数 / {len(calls)} 条 CALLS）===")
    entries = [f for f in funcs if indeg[f] == 0 and outdeg[f] > 0]
    middles = [f for f in funcs if indeg[f] > 0 and outdeg[f] > 0]
    leaves = [f for f in funcs if outdeg[f] == 0 and indeg[f] > 0]
    isolated = [f for f in funcs if indeg[f] == 0 and outdeg[f] == 0]

    if entries:
        print("\n▶ 入口（功能从这里开始执行，无人调用它们）：")
        for f in sorted(entries):
            print(f"    {f}  path= {ppath(nodes[f])}")
    if middles:
        print("\n↔ 中间（既被调用又调用别人）：")
        for f in sorted(middles):
            print(f"    {f}  path= {ppath(nodes[f])}")
    if leaves:
        print("\n◀ 叶子（只被调用，不调别人）：")
        for f in sorted(leaves):
            print(f"    {f}  path= {ppath(nodes[f])}")
    if isolated:
        print("\n· 孤立（无调用关系，可能独立工具或未连 CALLS）：")
        for f in sorted(isolated):
            print(f"    {f}  path= {ppath(nodes[f])}")

    print("\n调用边（调用者 → 被调用者，@调用点）：")
    for e in sorted(calls, key=lambda e: (e["from"], e["to"])):
        at = e.get("at_line", "?")
        loc = ploc(nodes[e['from']].get("path"), at)
        print(f"    {e['from'].rsplit('.', 1)[-1]} → {e['to'].rsplit('.', 1)[-1]}  @ {loc}")


def validate(data, scope=None, layer_num=None):
    """图完整性校验。范围控制：全量 / -l 层文件 / 关键词节点集。
    分级：Error（阻塞：悬空/path错/行号错/function缺path）vs Warning（提示：缺layer/weight/desc等历史欠账）。
    悬空边始终用全量节点集解析（跨文件引用合法，避免误报）。
    返回 Error 数（0=通过）。"""
    nodes_all = {n["id"]: n for n in data["nodes"]}
    edges_all = data["edges"]
    errors, warnings = [], []

    # 详情悬空检查（NodeDetails.toml 的 key 必须是合法节点 id；全局检查）
    for k in load_details():
        if k not in nodes_all:
            errors.append(f"[详情] NodeDetails.toml 的 key 悬空（非合法节点）: {k}")

    if layer_num is not None:
        layer_names = {p.name for p in base_dir().glob("Layer-*.toml") if p.name.startswith(f"Layer-{layer_num}-Graph")}
        scope_nodes = {nid: n for nid, n in nodes_all.items() if n.get("source") in layer_names}
        scope_edges = [e for e in edges_all if e.get("source") in layer_names]
        scope_desc = f"第 {layer_num} 层文件"
    elif scope:
        ids = fuzzy_find(data["nodes"], scope)
        if not ids:
            print(f"未找到匹配: {scope}")
            return 1
        scope_ids = set(ids)
        scope_nodes = {i: nodes_all[i] for i in ids if i in nodes_all}
        scope_edges = [e for e in edges_all if e["from"] in scope_ids or e["to"] in scope_ids]
        scope_desc = f"关键词 {scope!r}（{len(scope_nodes)} 节点及其关联边）"
    else:
        scope_nodes = nodes_all
        scope_edges = edges_all
        scope_desc = "全量"

    for nid, n in scope_nodes.items():
        for fld in ("id", "kind"):
            if fld not in n:
                errors.append(f"[节点] {nid} 缺必填字段 {fld}")
        kind = n.get("kind")
        if kind not in VALID_KINDS:
            errors.append(f"[节点] {nid} kind 非法: {kind!r}（合法: {'/'.join(sorted(VALID_KINDS))}）")
        if "path" not in n or not n.get("path"):
            if kind == "function":
                errors.append(f"[节点] {nid} function 缺 path（必须带 :行号）")
            else:
                warnings.append(f"[节点] {nid} 缺 path（feature 可省，file/module 建议填）")
        if "layer" not in n:
            warnings.append(f"[节点] {nid} 缺 layer（历史欠账，建议补）")
        elif n.get("layer") not in ARCH_LAYERS:
            warnings.append(f"[节点] {nid} layer 非法: {n.get('layer')!r}（合法: {'/'.join(sorted(ARCH_LAYERS))}）")
        if not n.get("desc"):
            warnings.append(f"[节点] {nid} 缺 desc（查询工具展示空白）")
        p = n.get("path")
        if p:
            filepart = re.sub(r":\d+$", "", p)
            full = get_repo() / filepart
            if not full.exists():
                errors.append(f"[节点] {nid} path 不存在: {p}")
            else:
                m = re.search(r":(\d+)$", p)
                if m:
                    ln = int(m.group(1))
                    lines = full.read_text(encoding="utf-8").splitlines()
                    target = lines[ln - 1] if ln <= len(lines) else ""
                    if kind == "function" and not re.search(r"def |class |async def ", target):
                        errors.append(f"[节点] {nid} 行号 {ln} 不是 def/class: {target.strip()[:50]}")

    for e in scope_edges:
        if e["from"] not in nodes_all:
            errors.append(f"[边] {e['from']} → {e['to']} ({e['rel']}) 起点悬空")
        if e["to"] not in nodes_all:
            errors.append(f"[边] {e['from']} → {e['to']} ({e['rel']}) 终点悬空")
        if e.get("rel") not in VALID_RELS:
            errors.append(f"[边] {e['from']} → {e['to']} rel 非法: {e.get('rel')!r}")
        if e.get("rel") == "CALLS" and "at_line" not in e:
            warnings.append(f"[边] {e['from']} → {e['to']} CALLS 缺 at_line（无法跳转调用现场）")
        if e.get("rel") == "DEPENDS_ON" and "weight" not in e:
            warnings.append(f"[边] {e['from']} → {e['to']} DEPENDS_ON 缺 weight（历史欠账）")

    if errors or warnings:
        print(f"⚠ 校验：{len(errors)} 错误 / {len(warnings)} 警告（范围: {scope_desc}，{len(scope_nodes)} 节点 / {len(scope_edges)} 边，全量节点 {len(nodes_all)}）")
        for pr in errors:
            print(f"  ✗ {pr}")
        for pr in warnings:
            print(f"  ⚠ {pr}")
        return len(errors)
    print(f"✓ 校验通过（范围: {scope_desc}，{len(scope_nodes)} 节点 / {len(scope_edges)} 边，全量节点 {len(nodes_all)}）")
    return 0


def resolve_src_path(filepath: str):
    """解析源码文件路径：绝对 → cwd → AX-GRAPH(BASE) → 仓库根。返回 Path 或 None。"""
    p = Path(filepath)
    if p.is_absolute():
        return p if p.exists() else None
    for cand in (Path.cwd() / p, BASE / p, get_repo() / p):
        if cand.exists():
            return cand
    return None


def init_file_graph(filepath: str) -> int:
    """为单个源码文件初始化 graph-for-<basename>.toml（AST 扫描顶层函数/类 + CALLS 边）。
    已存在则跳过（--file 查询时自动加载）。只读源码，生成图文件。"""
    import ast as _ast

    p = resolve_src_path(filepath)
    if p is None:
        print(f"文件不存在: {filepath}（查找范围: 当前目录 / AX-GRAPH / 仓库根）")
        return 1
    try:
        rel = str(p.resolve().relative_to(get_repo().resolve()))
    except ValueError:
        rel = filepath
    out = BASE / f"base-file-{p.stem}" / "Layer-1-Graph.toml"
    if out.exists():
        print(f"图已存在: base-file-{p.stem}/Layer-1-Graph.toml（--file 查询时自动加载；重建请删除目录后重跑）")
        return 0
    out.parent.mkdir(exist_ok=True)

    src = p.read_text(encoding="utf-8")
    try:
        tree = _ast.parse(src)
    except SyntaxError as e:
        print(f"解析失败: {e}")
        return 1

    # 顶层定义（函数/异步函数/类）
    defs = []
    for n in tree.body:
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            doc = ""
            if n.body and isinstance(n.body[0], _ast.Expr) and isinstance(n.body[0].value, _ast.Constant) and isinstance(n.body[0].value.value, str):
                doc = n.body[0].value.value.strip().split("\n")[0][:60]
            defs.append((n.name, n.lineno, doc))

    # CALLS：函数体内调用其他顶层定义（Name 调用，行号实测）
    top_names = {n[0] for n in defs}
    calls = []
    for name, _ln, _doc in defs:
        fn = next(n for n in tree.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)) and n.name == name)
        if isinstance(fn, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            for node in _ast.walk(fn):
                if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name) and node.func.id in top_names and node.func.id != name:
                    calls.append((name, node.func.id, node.lineno))

    # 生成 TOML
    mod = p.stem
    lines = [
        "# ============================================================",
        f"# 单文件图 — {rel}",
        "# 由 graph_query.py --file 自动初始化（AST 扫描），节点可手动扩充",
        "# ============================================================",
        "",
        "[graph]",
        f'name = "graph for {rel}"',
        'layer = 3',
        'granularity = "单文件图（文件+顶层函数+函数间CALLS）"',
        f'created = "2026-08-29"',
        f'source = "{rel}"',
        "",
        f'[[nodes]]  # 节点 file.{mod}: 文件本身',
        f'id = "file.{mod}"',
        'kind = "file"',
        f'path = "{rel}"',
        'layer = "infra"',
        f'desc = "{rel}"',
        "",
    ]
    for name, ln, doc in defs:
        lines += [
            f'[[nodes]]  # 节点 func.{mod}.{name}: 顶层定义',
            f'id = "func.{mod}.{name}"',
            'kind = "function"',
            f'path = "{rel}:{ln}"',
            'layer = "core"',
            f'desc = "{doc or "（无 docstring）"}"',
            "",
        ]
    lines += ["# 边：CONTAINS（函数归属文件）", ""]
    for name, _ln, _doc in defs:
        lines += ["[[edges]]", f'from = "file.{mod}"', f'to = "func.{mod}.{name}"', 'rel = "CONTAINS"', ""]
    if calls:
        lines += ["# 边：CALLS（函数间调用，AST 实测行号）", ""]
        for f, t, ln in sorted(calls):
            lines += ["[[edges]]", f"at_line = {ln}", f'from = "func.{mod}.{f}"', f'to = "func.{mod}.{t}"', 'rel = "CALLS"', ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    # base 元信息
    (out.parent / "base.toml").write_text(
        f'[base]\ntype = "file"\nsource = "{rel}"\nrepo = "{get_repo()}"\ndesc = "单文件图：{rel}"\n',
        encoding="utf-8",
    )
    print(f"✓ 已初始化 base-file-{p.stem}：{len(defs)} 个顶层定义 / {len(calls)} 条 CALLS 边")
    print(f"  查询: python3 graph_query.py --file {filepath} <节点id>")
    return 0


def load_file_graph(filepath: str) -> dict:
    """加载 base-file-<stem>/ 下全部 Layer-*.toml；不存在返回空数据。"""
    bd = BASE / f"base-file-{Path(filepath).stem}"
    if not bd.is_dir():
        return {"nodes": [], "edges": []}
    data = {"nodes": [], "edges": []}
    for p in sorted(bd.glob("Layer-*.toml")):
        with open(p, "rb") as f:
            d = tomllib.load(f)
        for n in d.get("nodes", []):
            n["source"] = p.name
        for e in d.get("edges", []):
            e["source"] = p.name
        data["nodes"].extend(d.get("nodes", []))
        data["edges"].extend(d.get("edges", []))
    return data


def main():
    parser = argparse.ArgumentParser(description="X-GRAPH 查询：查看节点第一层外围")
    parser.add_argument("query", nargs="?", help="节点 id 或关键词")
    parser.add_argument("-l", "--layer", help="过滤：数字=文件层(1/2)，或架构层名(core/interface/...)")
    parser.add_argument("-s", "--list", action="store_true", help="List 模式：只列出匹配节点，不展开详情")
    parser.add_argument("-e", "--explain", action="store_true", help="把关系翻译成中文解读（人话版）")
    parser.add_argument("-c", "--callchain", action="store_true", help="从入口展开调用链（树形+调用点行号）")
    parser.add_argument("-r", "--callers", action="store_true", help="反向调用链：谁在调用我")
    parser.add_argument("-b", "--build", action="store_true", help="构建/编辑节点详细介绍：--text 直写，缺省打开 $EDITOR(vim) 编辑临时文件")
    parser.add_argument("-d", "--detail", action="store_true", help="查询时在末尾显示该节点的详细介绍（NodeDetails.toml）")
    parser.add_argument("--text", help="配合 -b：直接写入的详细介绍文本（多行用 \\n）")
    parser.add_argument("--validate", action="store_true", help="图完整性校验：悬空边/path/行号/字段/详情key。范围=全部；配 -l 数字=某层文件；带关键词=匹配节点及其边")
    parser.add_argument("--purity", action="store_true", help="函数纯度分析：L0严格纯/L1工程纯/非纯/待验证 + 证据清单；一层调用者传递；只读不写盘（转发 purity.py）")
    parser.add_argument("--file", help="指定目标源码文件：自动初始化/加载 base-file-<stem>/ 单文件图，并作为查询/分析范围（可与 --purity 组合）")
    parser.add_argument("--base", help="切换并查询指定 base（同时设为默认，写入 .active-base）")
    parser.add_argument("--bases", action="store_true", help="列出全部 base（当前默认打 *）")
    parser.add_argument("--new-base", nargs=2, metavar=("TYPE", "PATH"), help="新建 base：dir <项目路径> | file <源码文件>")
    args = parser.parse_args()

    # base 管理：--bases / --new-base / --base 优先处理（切换后影响后续所有加载）
    if args.bases:
        active = get_active_base()
        print(f"当前默认: {active}\n")
        for name, meta in list_bases():
            mark = "*" if name == active else " "
            print(f"{mark} {name}  [{meta.get('type')}] source={meta.get('source')}  {meta.get('desc', '')}")
        sys.exit(0)
    if args.new_base:
        typ, path = args.new_base
        if typ == "dir":
            src = Path(path).expanduser().resolve()
            if not src.is_dir():
                print(f"目录不存在: {path}")
                sys.exit(1)
            name = f"base-dir-{src.name}"
            bd = BASE / name
            if bd.exists():
                print(f"已存在: {name}")
                sys.exit(1)
            bd.mkdir()
            (bd / "base.toml").write_text(
                f'[base]\ntype = "dir"\nsource = "{src}"\nrepo = "{src}"\ndesc = "项目图：{src.name}"\n',
                encoding="utf-8",
            )
            print(f"✓ 新建 base {name}（空图；手动加 Layer-*.toml，或 --new-base file 建单文件图）")
            sys.exit(0)
        elif typ == "file":
            sys.exit(init_file_graph(path))
        else:
            print("用法: --new-base dir <项目路径> | --new-base file <源码文件>")
            sys.exit(1)
    if args.base:
        if not (BASE / args.base).is_dir():
            print(f"未知 base: {args.base}（--bases 查看全部）")
            sys.exit(1)
        set_active_base(args.base)
        print(f"已切换默认 base → {args.base}")

    if args.validate:
        # 校验始终基于全量图（跨文件引用合法），范围控制：-l 层文件 / 关键词节点集
        full = load()
        if args.layer and args.layer.isdigit():
            rc = validate(full, layer_num=int(args.layer))
        else:
            rc = validate(full, scope=args.query if args.query else None)
        sys.exit(rc)

    if args.purity:
        if args.file:
            # 文件模式：批量分析该文件全部顶层函数（不依赖图节点）
            init_file_graph(args.file)
            try:
                from purity import purity_file_main
            except ImportError:
                print("缺少 purity.py（应在 AX-GRAPH 目录内）")
                sys.exit(1)
            sys.exit(purity_file_main(args.file, args.query if args.query else None))
        # 节点模式（默认项目图）
        full = load()
        if not args.query:
            print("用法: python3 graph_query.py --purity <节点id或关键词>")
            print("     纯度分级：L0 严格纯 / L1 工程纯(读全局无副作用) / 非纯 / 待验证")
            print("     或: python3 graph_query.py --purity --file <源码文件> [函数名]")
            sys.exit(1)
        matches = fuzzy_find(full["nodes"], args.query)
        if not matches:
            print(f"未找到匹配: {args.query}")
            sys.exit(1)
        try:
            from purity import purity_main
        except ImportError:
            print("缺少 purity.py（应在 AX-GRAPH 目录内）")
            sys.exit(1)
        sys.exit(purity_main(matches[0], full))

    if args.build:
        if not args.query:
            print("用法: python3 graph_query.py -b <节点id> [--text \"详细文本\"]")
            print("     缺省打开 $EDITOR（缺省 vim）编辑临时文件，保存退出后写入 NodeDetails.toml")
            sys.exit(1)
        sys.exit(build_detail(args.query, args.text))

    layer_num = args.layer if args.layer and args.layer.isdigit() else None
    arch = args.layer if args.layer in ARCH_LAYERS else None
    if args.layer and layer_num is None and arch is None:
        print(f"未知过滤值: {args.layer}（数字=文件层；架构层名: {'/'.join(sorted(ARCH_LAYERS))}）")
        return

    data = load(layer_num)
    if args.file:
        # --file：确保目标文件的单文件图存在并合并进查询范围
        init_file_graph(args.file)
        fg = load_file_graph(args.file)
        data["nodes"].extend(fg["nodes"])
        data["edges"].extend(fg["edges"])
    nodes = data["nodes"]
    if arch:
        nodes = [n for n in nodes if n.get("layer") == arch]

    q = args.query
    if not q:
        print("用法: python3 graph_query.py <节点id或关键词> [-l 过滤]")
        print("示例: graph_query.py mod.agent          # 全部层")
        print("      graph_query.py mod.agent -l 1     # 只看第一层文件的关系")
        print("      graph_query.py mod.agent -l core  # 只看 core 架构层")
        if arch:
            print(f"\n当前过滤: 架构层={arch}，可查节点：")
        elif layer_num:
            print(f"\n当前过滤: 文件层={layer_num}，可查节点（模块/簇）：")
        else:
            print("\n可查节点（模块/簇）：")
        for n in sorted(nodes, key=lambda x: x["id"]):
            if n["kind"] in ("module", "cluster"):
                print(f"  {n['id']}  {n.get('desc', '')}")
        return

    matches = fuzzy_find(nodes, q)
    if not matches:
        print(f"未找到匹配: {q}（试试 mod.agent / cluster.agent.adapters / file.agent.model_metadata）")
        return
    if args.list:
        node_map = {n["id"]: n for n in data["nodes"]}
        print(f"匹配 {len(matches)} 个节点（List 模式）：")
        for m in matches:
            n = node_map.get(m, {})
            print(f"  {m}  [{n.get('kind', '?')}]  path= {ppath(n) or '-'}  {n.get('desc', '')}")
        return
    if args.callchain:
        target = matches[0]
        kind = next((n.get("kind") for n in data["nodes"] if n["id"] == target), None)
        if kind == "feature":
            show_feature_callgraph(target, data)
        else:
            show_callchain(target, data)
    if args.callers:
        show_callers(matches[0], data)
    if not (args.callchain or args.callers):
        for m in matches:
            show(m, data, arch, args.explain)
        if args.detail:
            show_detail(matches[0], data)


if __name__ == "__main__":
    main()
