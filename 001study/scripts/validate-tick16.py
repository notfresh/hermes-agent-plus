#!/usr/bin/env python3
"""Structural validation for task001 state file (reproducible, offline).
Run: python3 validate-tick16.py ; exit 0 == pass"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))        # .../001study/scripts
ROOT = os.path.dirname(HERE)                              # .../001study
with open(os.path.join(ROOT, "task001-state.json"), encoding="utf-8") as f:
    s = json.load(f)

checks = []
def ok(cond, msg):
    checks.append((cond, msg))

ok(s["tick_count"] == 16, "tick_count == 16")
ok(s["phase"] in s["phase_order"], "phase in phase_order")
ok(s["awaiting_answer"] is True, "awaiting_answer is True")
ok(s["last_tick_time"].startswith("2026-08-02T00:2"), "last_tick_time 更新到本 tick")

reports = s["reports_generated"]
ok(len(reports) == 11 and len(set(reports)) == 11, "reports=11 无重复")
issues = s["issues_identified"]
nums = [i["number"] for i in issues]
ok(len(nums) == 12 and len(set(nums)) == 12, "issues=12 编号无重复")
for n in (76255, 76196, 76254, 76243):
    ok(n in nums, f"新候选 #{n} 已入库")
for i in issues:
    for k in ("number", "title", "labels", "difficulty", "status", "fix_point", "fix_idea"):
        ok(k in i, f"#{i.get('number')} 含字段 {k}")
# 磁盘报告文件 ↔ 登记表 交叉核对
for fname in sorted(os.listdir(ROOT)):
    if fname.startswith("issue-") and fname.endswith(".md"):
        ok(fname in reports, f"{fname} 已登记")

failed = [m for c, m in checks if not c]
for c, m in checks:
    print(("PASS " if c else "FAIL ") + m)
if failed:
    print(f"\n{len(failed)} FAILED")
    sys.exit(1)
print(f"\nALL {len(checks)} CHECKS PASSED")
