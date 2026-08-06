#!/usr/bin/env python3
"""Task001 tick28: 静默时段附带新池扫描 + 复查跟踪候选"""
import urllib.request, urllib.parse, json, sys

def api(path):
    req = urllib.request.Request(f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "task001-issue-scanner")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        return {"__err__": str(e)}

print("=== 1) 新 issue 池（created >= 2026-08-04T10:10:00Z，即 tick27 之后）===")
q = 'repo:NousResearch/hermes-agent is:issue created:>=2026-08-04T10:10:00Z'
url = "/search/issues?q=" + urllib.parse.quote(q) + "&sort=created&order=desc&per_page=30"
d = api(url)
if "__err__" in d or 'items' not in d:
    print(f"ERR: {d.get('__err__', str(d)[:120])}")
else:
    print(f"total: {d.get('total_count','?')}")
    for it in d['items']:
        if 'pull_request' in it: continue
        labs = ', '.join(l['name'] for l in it['labels'])[:70]
        print(f"  #{it['number']} [{it['created_at'][:16]}] {it['title'][:75]}")
        if labs: print(f"      labels: {labs}")

print("\n=== 2) 复查跟踪候选 ===")
for n in [75130, 78144, 78382]:
    it = api(f"/repos/NousResearch/hermes-agent/issues/{n}")
    if "__err__" in it:
        print(f"  #{n} ERR: {it['__err__'][:80]}")
        continue
    assignees = ', '.join(a['login'] for a in it.get('assignees', [])) or '无'
    print(f"  #{n} [{it['state']}] {it['title'][:65]}")
    print(f"      assignees: {assignees} | comments: {it['comments']} | updated: {it['updated_at'][:16]}")
    # timeline cross-refs
    tl = api(f"/repos/NousResearch/hermes-agent/issues/{n}/timeline?per_page=100")
    if isinstance(tl, list):
        refs = [ev for ev in tl if ev.get('event') == 'cross-referenced']
        for ev in refs[:6]:
            src = ev['source']['issue']
            t = 'PR' if 'pull_request' in src else 'issue'
            print(f"      cross-ref -> {t} #{src['number']}: {src['title'][:60]}")
        if not refs:
            print(f"      cross-refs: 无")
