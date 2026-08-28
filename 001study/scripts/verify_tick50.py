#!/usr/bin/env python3
"""tick 50 状态文件专项验证：JSON 语法 + 结构完整性 + 关键数据点"""
import json, py_compile, sys

STATE = "/root/projects/hermes-agent-plus/001study/task001-state.json"
SCRIPT = "/root/projects/hermes-agent-plus/001study/scripts/update_state_tick50.py"
failures = []

# 1) 更新脚本语法
try:
    py_compile.compile(SCRIPT, doraise=True)
    print("[PASS] update_state_tick50.py 语法 OK")
except py_compile.PyCompileError as e:
    failures.append(f"脚本语法错误: {e}")
    print("[FAIL] update_state_tick50.py 语法错误")

# 2) 状态文件 JSON 解析 + 关键字段
with open(STATE, encoding="utf-8") as f:
    s = json.load(f)

checks = [
    ("tick_count == 50", s["tick_count"] == 50),
    ("phase == issue_scanning", s["phase"] == "issue_scanning"),
    ("awaiting_answer is True", s["awaiting_answer"] is True),
    ("issues_identified 有 168 条", len(s["issues_identified"]) == 168),
    ("reports_generated 完整", len(s["reports_generated"]) == 20),
    ("code_reading 5 张卡", len(s["code_reading"]["cards_done"]) == 5),
]
for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        failures.append(name)

# 3) 关键 issue 条目存在性 + 8 字段齐全
nums = [str(i["number"]) for i in s["issues_identified"]]
required = ["84870", "85007", "85145", "85135", "85123", "85128", "79788", "84667", "84233"]
for n in required:
    if n not in nums:
        failures.append(f"缺少 issue #{n}")
        print(f"[FAIL] 缺少 issue #{n}")
    else:
        print(f"[PASS] issue #{n} 在列表中")

# 4) 新条目字段完整性
for n in ["85145", "85135", "85123", "85128"]:
    entry = next(i for i in s["issues_identified"] if str(i["number"]) == n)
    for k in ("number", "title", "labels", "difficulty", "status", "fix_point", "fix_idea", "notes"):
        if k not in entry or not entry[k]:
            failures.append(f"#{n} 缺字段 {k}")
            print(f"[FAIL] #{n} 缺字段 {k}")
    else:
        print(f"[PASS] #{n} 字段齐全")

# 5) 撞车/候选状态标记正确
e84870 = next(i for i in s["issues_identified"] if str(i["number"]) == "84870")
e85007 = next(i for i in s["issues_identified"] if str(i["number"]) == "85007")
if "已撞车" not in e84870["status"]:
    failures.append("#84870 状态未标记撞车")
    print("[FAIL] #84870 状态未标记撞车")
else:
    print("[PASS] #84870 已标记撞车")
if "已认领" not in e85007["status"]:
    failures.append("#85007 状态未标记认领")
    print("[FAIL] #85007 状态未标记认领")
else:
    print("[PASS] #85007 已标记认领")

# 6) 行号引用与源码核对
import re
src = open("/root/projects/hermes-agent-plus/gateway/run.py", encoding="utf-8", errors="replace").read()
lines = src.split("\n")
line_refs = [
    (20988, "compression_exhausted"),
    (13195, "compression_exhausted"),
]
for ln, needle in line_refs:
    if ln <= len(lines) and needle in lines[ln - 1]:
        print(f"[PASS] gateway/run.py:{ln} 含 {needle}")
    else:
        failures.append(f"gateway/run.py:{ln} 无 {needle}")
        print(f"[FAIL] gateway/run.py:{ln} 无 {needle}")

print()
if failures:
    print(f"共 {len(failures)} 项失败: {failures}")
    sys.exit(1)
print("全部检查通过 ✅")
