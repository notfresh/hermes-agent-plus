#!/usr/bin/env python3
"""AX-GRAPH 按节点更新（--update 支线，2026-09-04 用户拍板）

定位（用户定调 2026-09-04）：
    - 只接 function 节点（kind=function）；其他 kind 一律拒绝（YAGNI）
    - 默认行为：dry-run（打印 git diff 风格 diff，不写盘）——人在回路
    - --apply 才真写：改前 --validate，改后 --validate（保证无新错）

行为（第一版，最小可用）：
    1. 定位目标 function 节点（fuzzy_find）
    2. 对其 path 行号 grep 实际 def/class/async def 行号
    3. 若漂移：拼一条 diff（-旧 path / +新 path）
    4. dry-run 时只打印 diff；--apply 时改 TOML + 跑两次 validate

暂时不做（按 YAGNI 留 TODO）：
    - CALLS 边 at_line 同步刷新（用户首版只要 path 行号）
    - 批量更新（用户首版只要单点）
    - 多 base 联动（当前只操作默认 base）
    - 文件级/模块级节点更新（你明示"其他节点不接"）

参考：
    - How-to-update-graph.md §1 核心思路（按 commit 增量更新）
    - AGENTS.md §5 铁律 2（人在回路）
    - AGENTS.md §5 铁律 1（行号当次 grep 实测）
"""
import re
import subprocess
import sys
from pathlib import Path


# ---------- 路径与校验 ----------

def _resolve_node_path(node_path: str, repo: Path) -> Path:
    """节点的 path 是相对仓库根的，去掉 :行号 后拼绝对路径。"""
    filepart = re.sub(r":\d+(-?\d*)$", "", node_path)
    return repo / filepart


def _actual_def_line(filepath: Path, func_name: str) -> int | None:
    """grep 找该函数名的 def/class/async def 首行（行号）。

    策略：在文件里搜 `^\\s*(async )?def func_name\\b` 或 `^\\s*class func_name\\b`，
    取首个匹配。找不到返回 None。
    """
    if not filepath.exists():
        return None
    pattern = re.compile(rf"^\s*(async\s+)?def\s+{re.escape(func_name)}\b|^\s*class\s+{re.escape(func_name)}\b")
    try:
        with filepath.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if pattern.match(line):
                    return i
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _extract_func_name(nid: str) -> str | None:
    """func.graph_query.ppath → ppath；func.agent.skill_commands._load_skill_payload → _load_skill_payload。
    id 必须以 func. 开头，否则 None（其他 kind 不接）。"""
    if not nid.startswith("func."):
        return None
    return nid.rsplit(".", 1)[-1]


def _extract_current_line(node_path: str) -> int | None:
    """path = "X.py:84" → 84；path = "X.py:84-180" → 84（取起始行）；无 : 返回 None。"""
    m = re.search(r":(\d+)(?:-\d+)?$", node_path)
    return int(m.group(1)) if m else None


# ---------- TOML 读写 ----------

def _find_toml_for_node(node_id: str, base_meta: dict, repo: Path) -> tuple[Path, str] | None:
    """根据节点 source 字段找 TOML 文件。返回 (toml_path, layer_file_name)。

    节点 dict 有 'source' 字段（Layer-N-Graph-xxx.toml），base_dir() 是 base 根目录。
    file base（如 base-file-graph_query）下 TOML 名固定为 Layer-1-Graph.toml。
    """
    # 通过 load() 拿 source 字段；这里只接 path，需要外部传 data
    raise NotImplementedError("由 main() 传 node dict 进来")


# ---------- 主流程 ----------

def plan_update(nid: str, node: dict, repo: Path) -> dict:
    """计算一个节点的更新计划（不写盘）。

    返回 dict：
        {
            "nid": ...,
            "current_line": 84,
            "actual_line": 92,
            "needs_update": True,
            "diff_line": "-path = ...:84\\n+path = ...:92",
            "toml_path": Path("..."),
            "reason": "..." or None,
        }
    """
    node_path = node.get("path", "")
    func_name = _extract_func_name(nid)
    if func_name is None:
        return {"nid": nid, "needs_update": False, "reason": f"id={nid} 不是 func.* 节点，本命令不接（按 YAGNI）"}

    current_line = _extract_current_line(node_path)
    if current_line is None:
        return {"nid": nid, "needs_update": False, "reason": f"path={node_path!r} 无行号，跳过"}

    abs_path = _resolve_node_path(node_path, repo)
    actual_line = _actual_def_line(abs_path, func_name)
    if actual_line is None:
        return {"nid": nid, "needs_update": False, "reason": f"grep 未找到 def/class {func_name}（函数被删/重命名？）"}

    if actual_line == current_line:
        return {"nid": nid, "needs_update": False, "current_line": current_line, "reason": "行号无漂移"}

    # 拼 diff 行
    old_line = f'path = "{node_path}"'
    new_path = re.sub(r":\d+(-\d*)?$", f":{actual_line}", node_path)
    new_line = f'path = "{new_path}"'
    diff_line = f"-{old_line}\n+{new_line}"

    return {
        "nid": nid,
        "needs_update": True,
        "current_line": current_line,
        "actual_line": actual_line,
        "diff_line": diff_line,
        "old_path": node_path,
        "new_path": new_path,
        "toml_source": node.get("source", "?"),  # Layer-N-Graph-xxx.toml
    }


def do_apply(plan: dict, base_root: Path) -> tuple[bool, str]:
    """真改 TOML 文件。返回 (success, msg)。"""
    if not plan["needs_update"]:
        return False, "无需更新"
    toml_filename = plan.get("toml_source", "")
    if not toml_filename or toml_filename == "?":
        return False, f"节点无 source 字段，无法定位 TOML 文件"
    toml_path = base_root / toml_filename
    if not toml_path.exists():
        return False, f"TOML 文件不存在: {toml_path}"

    text = toml_path.read_text(encoding="utf-8")
    old_line = f'path = "{plan["old_path"]}"'
    new_line = f'path = "{plan["new_path"]}"'
    if old_line not in text:
        return False, f"原 path 行未在 TOML 中找到（{old_line}）"
    new_text = text.replace(old_line, new_line, 1)
    toml_path.write_text(new_text, encoding="utf-8")
    return True, f"已写盘: {toml_path}"


# ---------- 入口 ----------

def update_main(nid: str, data: dict, repo: Path, base_root: Path, apply: bool = False, force: bool = False) -> int:
    """--update 入口。

    默认 dry-run：打印 git diff 风格的 diff + 列出 reason。
    --apply 才真写：改前 --validate，改后 --validate（保证无新错）。
    --force：跳过改前 validate（用于修复本身就报错的图：行号漂移正是要修的目标）。
    """
    nodes = {n["id"]: n for n in data["nodes"]}
    node = nodes.get(nid)
    if not node:
        print(f"节点不存在: {nid}")
        return 1
    if node.get("kind") != "function":
        print(f"❌ --update 当前只支持 func.* 节点（kind=function）；传入了 kind={node.get('kind')}")
        return 1

    plan = plan_update(nid, node, repo)

    print(f"\n=== 更新计划：{nid} ===")
    print(f"  path= {node.get('path', '?')}  kind={node.get('kind')}  source={node.get('source', '?')}")

    if not plan["needs_update"]:
        print(f"  ✓ 无需更新：{plan.get('reason', '?')}")
        return 0

    print(f"  漂移: 行号 {plan['current_line']} → {plan['actual_line']}")
    print(f"  TOML: {plan.get('toml_source', '?')}")
    print()
    print(f"  计划改动：")
    for ln in plan["diff_line"].split("\n"):
        print(f"    {ln}")

    if not apply:
        print(f"\n  ⚠️ dry-run，未写盘。加 --apply 才真改。")
        return 0

    # apply
    if not force:
        print(f"\n  改前 validate：")
        rc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "graph_query.py"), "--validate", nid],
            cwd=repo,
        ).returncode
        if rc != 0:
            print(f"  ✗ 改前 validate 失败（exit={rc}）。如确认要修这个错误，加 --force 重试。")
            return rc or 1
    else:
        print(f"\n  ⚠️ --force 跳过改前 validate（你已知错误要修）")

    ok, msg = do_apply(plan, base_root)
    if not ok:
        print(f"  ✗ apply 失败：{msg}")
        return 1
    print(f"\n  ✓ {msg}")

    print(f"\n  改后 validate：")
    rc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "graph_query.py"), "--validate", nid],
        cwd=repo,
    ).returncode
    if rc != 0:
        print(f"  ✗ 改后 validate 失败（exit={rc}），请检查")
        return rc or 1

    print(f"\n  ✓ 全部完成。建议：git diff 看一下，确认 commit。")
    return 0


if __name__ == "__main__":
    print("用法: python3 graph_query.py --update <func_id> [--apply]")
    print("（update_graph 模块由 graph_query.py 转发调用，勿直接运行）")
    sys.exit(1)