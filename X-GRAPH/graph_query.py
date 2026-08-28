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
import tomllib
import difflib
import argparse
from pathlib import Path

BASE = Path(__file__).parent
ARCH_LAYERS = {"core", "interface", "capability", "application", "entry", "infra"}


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
    ids = [n["id"] for n in nodes]
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
    return f"{e['from']} --{rel}--> {e['to']}"


def show(nid, data, arch=None, explain=False):
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    node = nodes.get(nid)
    if not node:
        print(f"节点不存在: {nid}")
        return

    print(f"\n=== {nid} ===")
    print(f"  kind={node.get('kind')}  path= {node.get('path')}  layer={node.get('layer', '-')}  [{node.get('source', '')}]")
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


def main():
    parser = argparse.ArgumentParser(description="X-GRAPH 查询：查看节点第一层外围")
    parser.add_argument("query", nargs="?", help="节点 id 或关键词")
    parser.add_argument("-l", "--layer", help="过滤：数字=文件层(1/2)，或架构层名(core/interface/...)")
    parser.add_argument("--explain", action="store_true", help="把关系翻译成中文解读（人话版）")
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
    for m in matches:
        show(m, data, arch, args.explain)


if __name__ == "__main__":
    main()
