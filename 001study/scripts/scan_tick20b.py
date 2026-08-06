#!/usr/bin/env python3
"""Task001 tick20b: 验证标签 + 扫最新 open issues"""
import urllib.request, urllib.parse, json, time

def api(path):
    req = urllib.request.Request(f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "task001-issue-scanner")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        return {"__err__": str(e)}

# 1) 列出仓库标签，找好做类标签
print("===== 仓库标签（前 60 个） =====")
labs = api("/repos/NousResearch/hermes-agent/labels?per_page=60")
if isinstance(labs, list):
    for l in labs:
        print(f"  {l['name']}")
else:
    print(f"ERR: {str(labs)[:120]}")
time.sleep(0.3)

# 2) 扫最新创建的 open issues（最近 24-48h 的）
print("\n\n===== 最新 open issues (sort=created) =====")
d = api("/search/issues?q=" + urllib.parse.quote("repo:NousResearch/hermes-agent is:issue is:open") + "&sort=created&order=desc&per_page=30")
if 'items' in d:
    print(f"total open issues: {d.get('total_count')}")
    for it in d['items']:
        labs = ', '.join(l['name'] for l in it['labels'])[:60]
        print(f"  #{it['number']} [{it['created_at'][:10]}] {it['title'][:70]}")
        print(f"      {labs}")
else:
    print(f"ERR: {str(d)[:120]}")
