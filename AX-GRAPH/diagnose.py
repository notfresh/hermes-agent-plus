#!/usr/bin/env python3
"""AX-GRAPH 功能链诊断（--diagnose 支线）

目标：判断一条功能链（feature.*）是否符合"高内聚低耦合"的软件工程思维，
并给出**为什么**——具体证据（行号/边/调用点）、严重度、影响范围、阅读建议。

定位决策（2026-09-04 用户拍板）：
    - 与 --purity 平行的新支线（不是替代/上游）
    - 只读不写盘（人在回路：工具出诊断，人读、问、定夺）
    - 基于图里已有字段组合诊断，不发明新概念，不引入 tree-sitter/AST 全量分析

维度（第一版只实现 1，其余 TODO）：
    1. 内部依赖密度（功能链内部 CALLS 网络拓扑）
       - 内聚度：REALIZED_BY 函数之间的 CALLS 边占比（边数 / 理论最大）
       - 入口数量：孤立根（无被调）的入口有几个
       - 跨度：调用链最大深度
       - 跨图调用：实现函数调用链外函数的比例（"实现分散"的迹象）

后续维度（占位）：
    - 实现函数散落多少个 module（cluster 内聚的近似）
    - 与 feature 外部的依赖是否过重
"""

import json
import sys
from collections import Counter, deque


# ---------- 工具函数 ----------

def _short(fid: str) -> str:
    """func.agent.skill_commands._load_skill_payload → _load_skill_payload"""
    return fid.rsplit(".", 1)[-1]


def _path_line(node: dict) -> str:
    """节点 path:行号 表示（用于点击跳转）"""
    p = node.get("path", "?")
    ln = node.get("files+lines", "") or ""
    # files+lines 形如 "138-180"，取起始行
    line_start = ln.split("-")[0].strip() if ln else "?"
    return f"./{p}:{line_start}" if p != "?" else "?"


# ---------- 维度 1：内部依赖密度 ----------

def diagnose_internal_density(feature_id: str, data: dict) -> dict:
    """功能链内部 CALLS 网络诊断。

    返回结构化诊断 dict：
        {
            "category": "内部依赖密度",
            "target": feature_id,
            "metrics": {...},           # 客观指标
            "severity": "low|medium|high",
            "evidence": [...],          # 具体证据（id + 行号）
            "why_it_matters": str,
            "next_step_hint": str,
        }
    """
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]

    # 该 feature 的所有实现函数
    impl_funcs = [
        e["to"] for e in edges
        if e["from"] == feature_id
        and e["rel"] == "REALIZED_BY"
        and nodes.get(e["to"], {}).get("kind") == "function"
    ]
    fset = set(impl_funcs)

    # 内部 CALLS（实现函数之间的调用）
    internal_calls = [
        e for e in edges
        if e["rel"] == "CALLS" and e["from"] in fset and e["to"] in fset
    ]
    # 跨图调用（实现函数 → 图外函数）
    external_calls = [
        e for e in edges
        if e["rel"] == "CALLS" and e["from"] in fset and e["to"] not in fset
    ]
    # 反向：图外 → 实现函数
    incoming_external = [
        e for e in edges
        if e["rel"] == "CALLS" and e["to"] in fset and e["from"] not in fset
    ]

    n = len(impl_funcs)
    # 理论最大边数 = n*(n-1)（有向完全图，去掉自环）
    max_edges = n * (n - 1) if n > 1 else 0
    density = (len(internal_calls) / max_edges) if max_edges > 0 else 0.0

    indeg = Counter(e["to"] for e in internal_calls)
    outdeg = Counter(e["from"] for e in internal_calls)

    # 入口（indeg=0 且 outdeg>0）+ 叶子（outdeg=0 且 indeg>0）+ 孤立（indeg=0 且 outdeg=0）
    entries = [f for f in impl_funcs if indeg[f] == 0 and outdeg.get(f, 0) > 0]
    leaves = [f for f in impl_funcs if outdeg.get(f, 0) == 0 and indeg[f] > 0]
    isolated = [f for f in impl_funcs if indeg[f] == 0 and outdeg.get(f, 0) == 0]

    # 调用链最大深度（BFS 从任一入口出发）
    max_depth = _max_call_depth(entries or [f for f in impl_funcs if outdeg.get(f, 0) > 0],
                                internal_calls)

    # 散落 module 数（按 file.* 归属，按 module name 聚合）
    module_counter = Counter()
    for f in impl_funcs:
        fn = nodes.get(f, {})
        p = fn.get("path", "")
        # 顶层目录/文件作为 module 近似
        module_counter[p.split("/")[0] if p else "?"] += 1
    n_modules = len(module_counter)

    metrics = {
        "n_impl_funcs": n,
        "n_internal_calls": len(internal_calls),
        "max_internal_calls": max_edges,
        "internal_density": round(density, 3),
        "n_external_calls": len(external_calls),
        "n_incoming_external": len(incoming_external),
        "n_entries": len(entries),
        "n_leaves": len(leaves),
        "n_isolated": len(isolated),
        "max_call_depth": max_depth,
        "n_modules_scattered": n_modules,
        "top_modules": module_counter.most_common(3),
    }

    # 严重度判定（启发式、保守、基于图的客观量；不等于"工程好坏"，只标"值得看一下"）
    severity = "low"
    reasons = []

    # 入口过多：暗示实现分散，可能没有真正的"主路径"
    if len(entries) >= 3:
        severity = "medium"
        reasons.append(
            f"该功能有 {len(entries)} 个独立入口（indeg=0 且 outdeg>0），"
            f"说明这条链路可能由多个独立子流程拼成，建议读 feature 描述对照，"
            f"判断是设计如此（多入口合理）还是职责模糊"
        )

    # 外部调用过多：实现"溢出"到图外
    if len(external_calls) > 0 and n > 0 and len(external_calls) / n >= 1.0:
        # 平均每个实现函数向外调用 ≥ 1 次
        severity = "medium" if severity == "low" else "high"
        reasons.append(
            f"实现函数平均向外调用 {len(external_calls) / n:.1f} 次（链外），"
            f"共 {len(external_calls)} 条 CALLS 跨出本图——"
            f"实现分散在图外其他能力上，复用图外的 helper/工具时要警觉耦合"
        )

    # 散落 module 过多：实现跨 module
    if n_modules >= 4 and n >= 5:
        severity = "medium" if severity == "low" else severity
        reasons.append(
            f"实现函数散落在 {n_modules} 个 module（{dict(module_counter.most_common(3))}…），"
            f"跨 module 的功能实现维护成本更高；"
            f"若 module 是按职责划分的，那这种分散说明该功能横切多个职责"
        )

    # 调用链深度过深
    if max_depth >= 5:
        severity = "medium" if severity == "low" else severity
        reasons.append(
            f"调用链最大深度 = {max_depth}，读这条链路需要跨越 ≥{max_depth} 层调用栈，"
            f"理解成本随深度指数级上升"
        )

    # 密度过高（耦合警告）
    if density >= 0.6 and n >= 5:
        severity = "medium" if severity == "low" else severity
        reasons.append(
            f"内部 CALLS 密度 = {density:.2f}（{len(internal_calls)}/{max_edges}），"
            f"实现函数两两之间大量互相依赖——可能是合理（紧凑内核）"
            f"也可能是高耦合（改一个牵一片）"
        )

    if not reasons:
        reasons.append(
            f"实现函数 {n} 个 / 内部边 {len(internal_calls)} 条 / 散落 {n_modules} module / "
            f"深度 {max_depth}——结构紧凑，未触发启发式警告"
        )

    return {
        "category": "内部依赖密度",
        "target": feature_id,
        "metrics": metrics,
        "severity": severity,
        "evidence": [
            f"REALIZED_BY 函数: {', '.join(_short(f) for f in impl_funcs[:6])}{'...' if len(impl_funcs) > 6 else ''}",
            f"内部 CALLS: {len(internal_calls)} 条 / 跨图 CALLS: {len(external_calls)} 条 / 反向跨图: {len(incoming_external)} 条",
            f"入口={len(entries)} 叶子={len(leaves)} 孤立={len(isolated)}",
        ],
        "why_it_matters": (
            "功能链的「内聚」指的是所有实现函数是否在描述一个清晰的事；"
            "「耦合」指是否依赖过多外部能力。"
            "结构上看：入口过多=职责可能模糊；外部调用过多=能力溢出；"
            "module 散落过多=横切多个职责；调用链深=理解成本高；密度过高=改一个牵一片。"
        ),
        "next_step_hint": "; ".join(reasons),
    }


def _max_call_depth(start_nodes: list, internal_calls: list) -> int:
    """BFS 求最大调用深度（避免环路：visited 集合）。返回 0 当 start 为空。"""
    if not start_nodes:
        return 0
    adj = {}
    for e in internal_calls:
        adj.setdefault(e["from"], []).append(e["to"])

    max_d = 0
    for s in start_nodes:
        # BFS
        queue = deque([(s, 1)])
        visited = {s}
        while queue:
            cur, d = queue.popleft()
            max_d = max(max_d, d)
            for nxt in adj.get(cur, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, d + 1))
    return max_d


# ---------- 入口 ----------

def diagnose_main(nid: str, data: dict, as_json: bool = False) -> int:
    """--diagnose 入口：分析并打印报告。只读不写盘。

    nid 必须指向一个 feature.* 节点；其它 kind 一律拒绝（避免误用）。
    """
    nodes = {n["id"]: n for n in data["nodes"]}
    node = nodes.get(nid)
    if not node:
        print(f"节点不存在: {nid}")
        return 1
    if node.get("kind") != "feature":
        print(f"❌ --diagnose 当前只支持 feature.* 节点（kind=feature）；传入了 kind={node.get('kind')}")
        print(f"   后续会扩展支持 module/file/function，敬请期待")
        return 1

    report = diagnose_internal_density(nid, data)

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # 人话输出
    print(f"\n=== 功能链诊断：{nid} ===")
    print(f"  path= {node.get('path', '?')}  kind={node.get('kind')}  layer={node.get('layer', '-')}")
    if node.get("desc"):
        print(f"  desc: {node['desc']}")

    sev = report["severity"]
    sev_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(sev, "⚪")
    print(f"\n  [{sev_icon} {sev}] {report['category']}")

    m = report["metrics"]
    print(f"\n  客观指标：")
    print(f"    实现函数数 = {m['n_impl_funcs']}")
    print(f"    内部 CALLS = {m['n_internal_calls']} / 理论最大 {m['max_internal_calls']}（密度 {m['internal_density']}）")
    print(f"    跨图 CALLS = {m['n_external_calls']}（向外）/{m['n_incoming_external']}（反向）")
    print(f"    入口/叶子/孤立 = {m['n_entries']}/{m['n_leaves']}/{m['n_isolated']}")
    print(f"    调用链最大深度 = {m['max_call_depth']}")
    print(f"    散落 module 数 = {m['n_modules_scattered']}{('（' + str(m['top_modules']) + '）') if m['n_modules_scattered'] else ''}")

    print(f"\n  证据：")
    for e in report["evidence"]:
        print(f"    · {e}")

    print(f"\n  为什么这件事值得关心：")
    print(f"    {report['why_it_matters']}")

    print(f"\n  建议下一步：")
    print(f"    {report['next_step_hint']}")

    print(f"\n  ⚠️ 提示：诊断仅基于图证据，'符合软件工程思维' 的最终判断仍需人读代码。")
    return 0


if __name__ == "__main__":
    # 直接运行模式：python3 diagnose.py <feature_id>
    if len(sys.argv) < 2:
        print("用法: python3 diagnose.py <feature_id> [--json]")
        sys.exit(1)
    nid = sys.argv[1]
    as_json = "--json" in sys.argv

    # 复用 graph_query.load()
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from graph_query import load
    except ImportError:
        print("缺少 graph_query.py（应在 AX-GRAPH 目录内）")
        sys.exit(1)

    data = load()
    sys.exit(diagnose_main(nid, data, as_json=as_json))