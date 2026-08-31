#!/usr/bin/env python3
"""AX-GRAPH 函数纯度分析（--purity 支线）

判定标准（用户定调 2026-08-29）：
    L0 严格纯   —— 只用参数和局部变量，只 return 结果
    L1 工程纯   —— 可读外部常量/配置（读全局），但绝不写外部、无副作用
    非纯        —— 写全局 / 改对象属性或下标 / 修改型方法调用 / 副作用 builtins / 调用图内非纯函数
    附注(ℹ)     —— 方法调用（非修改型）、调用未入图函数、动态特性：记录不降级，人自行判断

规则：
    1. 只读分析，绝不写盘（与"人在回路"协作原则一致）
    2. 一层调用者传递：A 调 B，B 非纯 → A 非纯（依赖图里实测的 CALLS 边，不猜）
    3. 保守但不武断：修改型方法走已知集合（append/write/...），集合外的对象方法只记录不降级
    4. 测不了标"待验证/附注"，不装精确

已知误报源（人复核时注意）：
    - A 把私有临时对象传给 B，B 修改它不泄漏 → 静态分析会保守降级 A
    - 方法调用语义（str.upper 纯 vs obj.custom_mutate 修改）AST 看不出 → 只记录
"""
import ast
import builtins as _b
import sys
from pathlib import Path

BUILTINS = set(dir(_b))
# 已知修改型方法（对象变异语义）
MUTATING_METHODS = {
    "append", "update", "setdefault", "add", "extend", "insert", "remove",
    "pop", "clear", "sort", "reverse", "write", "writelines", "send", "put",
    "push", "discard", "__setitem__", "difference_update", "intersection_update",
    "symmetric_difference_update",
}
# 已知副作用 builtins（print 已排除：控制台输出不影响数据加工，用户定调 2026-08-29）
SIDE_EFFECT_BUILTINS = {
    "open", "exec", "eval", "input", "breakpoint", "exit", "quit",
    "compile", "globals", "locals", "vars", "setattr", "delattr",
}


def _load_file(path: str):
    p = Path(path)
    if not p.is_absolute():
        try:
            from graph_query import get_repo
            p = get_repo() / p
        except ImportError:
            p = Path(__file__).parent.parent / p
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def find_function(tree, lineno: int):
    """在 AST 里找定义行号 == lineno 的函数/类节点。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.lineno == lineno:
                return node
    return None


def param_names(fn) -> set:
    a = fn.args
    names = [x.arg for x in a.posonlyargs] + [x.arg for x in a.args] + [x.arg for x in a.kwonlyargs]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return set(names)


def collect_locals(fn):
    """第一遍：收集局部名 + global/nonlocal 声明（两遍遍历避免顺序依赖）。"""
    locals_ = set()
    gdecl, ndecl = set(), set()
    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node is not fn:
                locals_.add(node.name)
        elif isinstance(node, ast.ClassDef):
            locals_.add(node.name)
        elif isinstance(node, ast.Lambda):
            for x in node.args.args:
                locals_.add(x.arg)
            if node.args.vararg:
                locals_.add(node.args.vararg.arg)
            if node.args.kwarg:
                locals_.add(node.args.kwarg.arg)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                        locals_.add(n.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)) and node.target:
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    locals_.add(n.id)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    for n in ast.walk(item.optional_vars):
                        if isinstance(n, ast.Name):
                            locals_.add(n.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            locals_.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                locals_.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.NamedExpr):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    locals_.add(n.id)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                for n in ast.walk(gen.target):
                    if isinstance(n, ast.Name):
                        locals_.add(n.id)
        elif isinstance(node, ast.Global):
            gdecl.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            ndecl.update(node.names)
    return locals_, gdecl, ndecl


def _root_name(node):
    """Attribute/Subscript 链的根 Name（a.b.c → 'a'；a.setdefault(...).append → 'a'）；
    无法解析的 Call 返回值/字面量 → None（保守）。"""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Call):
        # 链式方法调用的返回值（dict.setdefault(...) 返回 dict 自身）穿透解析
        f = node.func
        if isinstance(f, ast.Attribute):
            return _root_name(f.value)
        return None
    if isinstance(node, ast.Name):
        return node.id
    return None


def analyze_ast(fn, file_path: str, module_names: set = None):
    """第二遍：收集读全局/写外部/副作用调用/方法调用/动态特性。
    module_names：模块级 def/class/import 名（函数引用不算读全局变量）。
    关键区分：改参数对象/全局对象 = 外部副作用（降级）；改自建局部对象 = 局部加工（不降级）。"""
    module_names = module_names or set()
    params = param_names(fn)
    locals_, gdecl, ndecl = collect_locals(fn)
    fn_name = fn.name
    reads, writes, side_calls = [], [], []
    method_calls, unknown_calls, dynamics, local_ops = [], [], [], []

    for node in ast.walk(fn):
        if node is fn:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in params or node.id in locals_ or node.id in BUILTINS:
                continue
            if node.id == fn_name or node.id in module_names:
                continue
            tag = "读全局(global声明)" if node.id in gdecl else "读全局"
            reads.append((node.id, node.lineno, tag))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id in (gdecl | ndecl):
                    writes.append((t.id, t.lineno, "写全局(声明)"))
                elif isinstance(t, ast.Name) and t.id not in locals_ and t.id not in params:
                    writes.append((t.id, t.lineno, "写全局"))
                elif isinstance(t, (ast.Attribute, ast.Subscript)):
                    root = _root_name(t)
                    if root is None:
                        writes.append((ast.unparse(t)[:60], t.lineno, "修改未知根对象(保守)"))
                    elif root in locals_:
                        local_ops.append((ast.unparse(t)[:60], t.lineno, "修改自建局部对象"))
                    elif root in params:
                        writes.append((ast.unparse(t)[:60], t.lineno, "修改参数对象"))
                    else:
                        writes.append((ast.unparse(t)[:60], t.lineno, "修改全局对象"))
        elif isinstance(node, ast.Delete):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id not in locals_ and t.id not in params:
                    writes.append((t.id, t.lineno, "del 全局"))
                elif isinstance(t, (ast.Attribute, ast.Subscript)):
                    writes.append((ast.unparse(t)[:60], t.lineno, "del 对象成员"))
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                if f.id in SIDE_EFFECT_BUILTINS:
                    side_calls.append((f.id, node.lineno, "内置副作用函数"))
                elif f.id in (params | locals_):
                    method_calls.append((ast.unparse(f)[:50], node.lineno, "调用函数变量(保守)"))
                elif f.id not in BUILTINS:
                    unknown_calls.append((f.id, node.lineno))
            elif isinstance(f, ast.Attribute):
                if isinstance(f.value, ast.Constant):
                    pass  # 字面量方法调用，纯（如 "x".upper()）
                elif f.attr in MUTATING_METHODS:
                    root = _root_name(f.value)
                    if root is None:
                        side_calls.append((ast.unparse(f)[:50], node.lineno, "修改未知根对象(保守)"))
                    elif root in locals_:
                        local_ops.append((ast.unparse(f)[:50], node.lineno, "局部对象方法"))
                    elif root in params:
                        side_calls.append((ast.unparse(f)[:50], node.lineno, "修改参数对象"))
                    else:
                        side_calls.append((ast.unparse(f)[:50], node.lineno, "修改外部对象"))
                else:
                    method_calls.append((ast.unparse(f)[:50], node.lineno, "对象方法(语义未知)"))
            else:
                method_calls.append((ast.unparse(f)[:50], node.lineno, "复杂调用(保守)"))
        elif isinstance(node, ast.Call) is False:
            pass

    # 动态特性：getattr/setattr 动态访问（setattr 已在副作用；getattr 读属性动态）
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            dynamics.append((f"getattr 动态访问 @{node.lineno}", node.lineno))

    return {
        "reads": reads, "writes": writes, "side_calls": side_calls,
        "method_calls": method_calls, "unknown_calls": unknown_calls,
        "dynamics": dynamics, "local_ops": local_ops,
    }


EMPTY_REPORT = {
    "reads": [], "writes": [], "side_calls": [],
    "method_calls": [], "unknown_calls": [], "dynamics": [],
    "local_ops": [], "callee_nonpure": [],
}


def analyze_node(nid: str, nodes: dict, edges: list, depth: int = 0, visited: set = None):
    """分析节点纯度。depth<1 时做一层调用者传递。返回 (level, 报告dict)。"""
    visited = visited or set()
    if nid in visited:
        return "L0", {**EMPTY_REPORT, "note": "（循环引用，跳过重复分析）"}
    visited = visited | {nid}
    node = nodes.get(nid, {})
    path = node.get("path")
    if not path or ":" not in path:
        return "待验证", {**EMPTY_REPORT, "note": f"节点无 path/行号（kind={node.get('kind')}），无法 AST 分析"}

    filepart, _, lnstr = path.rpartition(":")
    try:
        lineno = int(lnstr)
    except ValueError:
        return "待验证", {**EMPTY_REPORT, "note": f"path 行号非法: {path}"}
    src = _load_file(filepart)
    if src is None:
        return "待验证", {**EMPTY_REPORT, "note": f"文件不存在: {filepart}"}
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return "待验证", {**EMPTY_REPORT, "note": f"文件解析失败: {e}"}
    fn = find_function(tree, lineno)
    if fn is None:
        return "待验证", {**EMPTY_REPORT, "note": f"行号 {lineno} 处无 def/class（行号漂移？跑 --suggest 查建议）"}

    # 模块级 def/class/import 名：函数引用不算读全局变量
    module_names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                module_names.add(a.asname or a.name.split(".")[0])

    r = analyze_ast(fn, filepart, module_names)

    # ── 一层调用者传递（只深挖一层，依赖图里实测 CALLS 边）──
    callee_nonpure = []
    if depth < 1:
        for e in edges:
            if e.get("rel") == "CALLS" and e["from"] == nid and e["to"] in nodes:
                sub_level, sub = analyze_node(e["to"], nodes, edges, depth + 1, visited)
                if sub_level in ("非纯", "待验证"):
                    callee_nonpure.append((e["to"], e.get("at_line"), sub_level, sub))

    # ── 评级 ──
    level = "L0"
    if r["writes"] or r["side_calls"]:
        level = "非纯"
    elif callee_nonpure:
        level = "非纯"
    elif r["reads"]:
        level = "L1"

    report = {
        "reads": r["reads"], "writes": r["writes"], "side_calls": r["side_calls"],
        "method_calls": r["method_calls"], "unknown_calls": r["unknown_calls"],
        "dynamics": r["dynamics"], "local_ops": r["local_ops"],
        "callee_nonpure": callee_nonpure,
    }
    return level, report


def _sub_summary(sub: dict) -> str:
    """被调函数非纯摘要（writes/side_calls 第一条或 note）。"""
    if sub.get("note"):
        return sub["note"]
    for key, label in (("writes", "写"), ("side_calls", "副作用调用")):
        if sub.get(key):
            item = sub[key][0]
            if isinstance(item, tuple):
                return f"{label} {item[0]} @{item[1]}"
            return f"{label} {item}"
    return "非纯(见其自身报告)"


def purity_main(nid: str, data: dict) -> int:
    """--purity 入口：分析并打印报告。只读不写盘。"""
    nodes = {n["id"]: n for n in data["nodes"]}
    edges = data["edges"]
    node = nodes.get(nid)
    if not node:
        print(f"节点不存在: {nid}")
        return 1

    level, r = analyze_node(nid, nodes, edges)

    print(f"\n=== 纯度分析：{nid} ===")
    print(f"  path= ./{node.get('path', '?')}  kind={node.get('kind')}")
    print(f"  评级: ", end="")
    if level == "L0":
        print("✅ L0 严格纯 —— 只用参数和局部变量，只 return 结果，可放心单独阅读")
    elif level == "L1":
        print("✅ L1 工程纯 —— 读外部但无副作用，基本可单独阅读（注意下面读的全局）")
    elif level == "非纯":
        print("❌ 非纯 —— 有副作用，单独阅读时必须追踪影响面")
    else:
        print("⚠ 待验证 —— 无法可靠判定")
        if r.get("note"):
            print(f"      原因: {r['note']}")

    # 证据块
    blocks = []
    if r["writes"]:
        blocks.append(("✗ 写外部", [f"{name} @{ln}（{tag}）" for name, ln, tag in r["writes"]]))
    if r["side_calls"]:
        blocks.append(("✗ 副作用调用", [f"{name} @{ln}（{tag}）" for name, ln, tag in r["side_calls"]]))
    if r["callee_nonpure"]:
        blocks.append(("✗ 调用非纯函数（一层传递）", [
            f"{name} @{at or '?'} → {lvl}: {_sub_summary(sub)}"
            for name, at, lvl, sub in r["callee_nonpure"]
        ]))
    if r["reads"]:
        blocks.append(("ℹ 读全局", [f"{name} @{ln}（{tag}）" for name, ln, tag in r["reads"]]))
    if r["method_calls"]:
        blocks.append(("ℹ 方法调用（语义未知，未降级）", [f"{name} @{ln}（{tag}）" for name, ln, tag in r["method_calls"]]))
    if r["unknown_calls"]:
        blocks.append(("ℹ 调用未入图函数（不判定，人自行判断）", [f"{name} @{ln}" for name, ln in r["unknown_calls"]]))
    if r["dynamics"]:
        blocks.append(("ℹ 动态特性", [f"{name}" for name, _ln in r["dynamics"]]))
    if r["local_ops"]:
        blocks.append(("ℹ 局部加工（改自建局部对象，不降级）", [f"{name} @{ln}（{tag}）" for name, ln, tag in r["local_ops"]]))

    for title, items in blocks:
        print(f"\n  {title}:")
        for it in items:
            print(f"    · {it}")

    if not blocks:
        print("\n  （无任何外部依赖/副作用证据）")
    return 0


def purity_file_main(filepath: str, func_name: str = None) -> int:
    """--purity --file 模式：批量分析文件所有顶层函数纯度（不依赖图）。
    func_name 指定时只分析该函数。只读不写盘。"""
    import ast as _ast

    # 复用 graph_query 的路径解析（三候选：cwd / AX-GRAPH / 仓库根）
    try:
        from graph_query import resolve_src_path
    except ImportError:
        p = Path(filepath)
        if not p.is_absolute():
            for cand in (Path.cwd() / p, Path(__file__).parent / p):
                if cand.exists():
                    p = cand
                    break
    else:
        p = resolve_src_path(filepath)
    if p is None or not p.exists():
        print(f"文件不存在: {filepath}（查找范围: 当前目录 / AX-GRAPH / 仓库根）")
        return 1
    src = _load_file(str(p))
    if src is None:
        print(f"文件不存在: {filepath}")
        return 1
    try:
        tree = _ast.parse(src)
    except SyntaxError as e:
        print(f"解析失败: {e}")
        return 1

    module_names = set()
    defs = []
    for n in tree.body:
        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            module_names.add(n.name)
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                defs.append(n)
        elif isinstance(n, (_ast.Import, _ast.ImportFrom)):
            for a in n.names:
                module_names.add(a.asname or a.name.split(".")[0])

    if func_name:
        # 兼容节点 id 格式（func.<mod>.<name>）→ 提取函数名；也支持裸函数名
        if "." in func_name:
            func_name = func_name.rsplit(".", 1)[-1]
        matched = [n for n in defs if n.name == func_name]
        if not matched:
            print(f"文件 {filepath} 中未找到函数: {func_name}")
            return 1
        defs = matched

    print(f"\n=== 纯度扫描：{filepath}（{len(defs)} 个函数）===")
    nonpure = []
    for fn in defs:
        r = analyze_ast(fn, str(p), module_names)
        level = "非纯" if (r["writes"] or r["side_calls"]) else ("L1" if r["reads"] else "L0")
        if level == "非纯":
            nonpure.append((fn.name, r))
        # 摘要
        summary = []
        if r["writes"]:
            summary.append(f"{len(r['writes'])}处写外部")
        if r["side_calls"]:
            summary.append(f"{len(r['side_calls'])}处副作用")
        if r["reads"]:
            summary.append(f"{len(r['reads'])}处读全局")
        if r["local_ops"]:
            summary.append(f"{len(r['local_ops'])}处局部加工")
        if r["method_calls"]:
            summary.append(f"{len(r['method_calls'])}处方法")
        mark = {"L0": "✅", "L1": "🟡", "非纯": "❌"}[level]
        print(f"  {mark} {fn.name:28s} @{fn.lineno:<5d} {level:3s}  {', '.join(summary) if summary else '无外部依赖'}")

    if nonpure:
        print("\n── 非纯函数证据 ──")
        for name, r in nonpure:
            print(f"  ❌ {name}:")
            for w in r["writes"]:
                print(f"      ✗ 写 {w[0]} @{w[1]}（{w[2]}）")
            for s in r["side_calls"]:
                print(f"      ✗ 副作用 {s[0]} @{s[1]}（{s[2]}）")
    return 0


if __name__ == "__main__":
    print("用法: python3 graph_query.py --purity <节点id>")
    print("（purity 模块由 graph_query.py 转发调用，勿直接运行）")
    sys.exit(1)
