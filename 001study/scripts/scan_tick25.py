#!/usr/bin/env python3
"""Task001 tick25: 附带新池扫描（用户决策 B 后降为低优先级）"""
import urllib.request, urllib.parse, json

def api(path):
    req = urllib.request.Request(f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "task001-issue-scanner")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        return {"__err__": str(e)}

seen = set()
for label in ["good first issue", "help wanted", "easy"]:
    q = f'repo:NousResearch/hermes-agent is:issue is:open label:"{label}"'
    url = "/search/issues?q=" + urllib.parse.quote(q) + "&sort=created&order=desc&per_page=10"
    d = api(url)
    if "__err__" in d or 'items' not in d:
        print(f"label={label} ERR: {d.get('__err__', str(d)[:80])}")
        continue
    print(f"\n--- label={label}: total={d.get('total_count','?')} ---")
    for it in d['items']:
        if it['number'] in seen: continue
        seen.add(it['number'])
        print(f"  #{it['number']} [{it['created_at'][:10]}] {it['title'][:70]}")

print("\n--- 新 issue 池（created > 2026-08-03T12:00:00Z）---")
q2 = 'repo:NousResearch/hermes-agent is:issue created:>=2026-08-03T12:00:00Z'
url2 = "/search/issues?q=" + urllib.parse.quote(q2) + "&sort=created&order=desc&per_page=30"
d2 = api(url2)
if "__err__" in d2 or 'items' not in d2:
    print(f"ERR: {d2.get('__err__', str(d2)[:80])}")
else:
    print(f"total: {d2.get('total_count','?')}")
    for it in d2['items']:
        if 'pull_request' in it: continue
        labs = ', '.join(l['name'] for l in it['labels'])[:60]
        print(f"  #{it['number']} [{it['created_at'][:16]}] {it['title'][:70]}")
        if labs: print(f"      labels: {labs}")
