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
ARCH_LAYERS = {"core", "interface", "capability", "application", "entry", "infra"}
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
    """合并加载同目录所有 Layer-*-Graph.toml；layer_num 指定时只加载对应文件"""
    data = {"nodes": [], "edges": []}
    files = sorted(BASE.glob("Layer-*.toml"))
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
        d = nodes.get(e["to"], {}).get("desc", "")[:36]
        print(f"  [{e['rel']}] → {e['to']}{w}  {d}{note}")

    if arch:
        print(f"\n-- 入边 {len(inn)} 条（谁 → {nid}，仅{arch}层）--")
    else:
        print(f"\n-- 入边 {len(inn)} 条（谁 → {nid}）--")
    for e in sorted(inn, key=lambda e: (e["rel"], e["from"])):
        w = f"  weight={e['weight']}" if e.get("weight") else ""
        note = f"  [{e['note']}]" if e.get("note") else ""
        d = nodes.get(e["from"], {}).get("desc", "")[:36]
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


def main():
    parser = argparse.ArgumentParser(description="X-GRAPH 查询：查看节点第一层外围")
    parser.add_argument("query", nargs="?", help="节点 id 或关键词")
    parser.add_argument("-l", "--layer", help="过滤：数字=文件层(1/2)，或架构层名(core/interface/...)")
    parser.add_argument("-s", "--list", action="store_true", help="List 模式：只列出匹配节点，不展开详情")
    parser.add_argument("-e", "--explain", action="store_true", help="把关系翻译成中文解读（人话版）")
    parser.add_argument("-c", "--callchain", action="store_true", help="从入口展开调用链（树形+调用点行号）")
    parser.add_argument("-r", "--callers", action="store_true", help="反向调用链：谁在调用我")
    args = parser.parse_args()

    layer_num = args.layer if args.layer and args.layer.isdigit() else None
    arch = args.layer if args.layer in ARCH_LAYERS else None
    if args.layer and layer_num is None and arch is None:
        print(f"未知过滤值: {args.layer}（数字=文件层；架构层名: {'/'.join(sorted(ARCH_LAYERS))}）")
        return

    data = load(layer_num)
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
                print(f"  {n['id']}  {n.get('desc', '')[:44]}")
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
            print(f"  {m}  [{n.get('kind', '?')}]  path= {ppath(n) or '-'}  {n.get('desc', '')[:36]}")
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


if __name__ == "__main__":
    main()
