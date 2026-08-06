#!/usr/bin/env python3
"""Task001 tick28b: 细看新池候选 issue + 补翻新池剩余页"""
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

print("=== 新池剩余页（page 2）===")
q = 'repo:NousResearch/hermes-agent is:issue created:>=2026-08-04T10:10:00Z'
url = "/search/issues?q=" + urllib.parse.quote(q) + "&sort=created&order=desc&per_page=30&page=2"
d = api(url)
if "__err__" in d or 'items' not in d:
    print(f"ERR: {d.get('__err__', str(d)[:120])}")
else:
    for it in d['items']:
        if 'pull_request' in it: continue
        labs = ', '.join(l['name'] for l in it['labels'])[:70]
        print(f"  #{it['number']} [{it['created_at'][:16]}] {it['title'][:75]}")
        if labs: print(f"      labels: {labs}")

for n in [78600, 78580, 78519, 78598]:
    print(f"\n{'='*70}\n### #{n}")
    it = api(f"/repos/NousResearch/hermes-agent/issues/{n}")
    if "__err__" in it:
        print(f"ERR: {it['__err__'][:100]}"); continue
    assignees = ', '.join(a['login'] for a in it.get('assignees', [])) or '无'
    labs = ', '.join(l['name'] for l in it['labels']) or '无'
    print(f"[{it['state']}] {it['title']}")
    print(f"author: {it['user']['login']} | created: {it['created_at'][:16]} | updated: {it['updated_at'][:16]}")
    print(f"assignees: {assignees} | comments: {it['comments']} | labels: {labs}")
    body = (it.get('body') or '')[:1500]
    print(f"--- body ---\n{body}")
    tl = api(f"/repos/NousResearch/hermes-agent/issues/{n}/timeline?per_page=100")
    if isinstance(tl, list):
        refs = [ev for ev in tl if ev.get('event') == 'cross-referenced']
        for ev in refs[:5]:
            src = ev['source']['issue']
            t = 'PR' if 'pull_request' in src else 'issue'
            print(f"  cross-ref -> {t} #{src['number']}: {src['title'][:60]}")
        if not refs: print("  cross-refs: 无")
    cm = api(f"/repos/NousResearch/hermes-agent/issues/{n}/comments?per_page=10")
    if isinstance(cm, list) and cm:
        print(f"--- comments ({len(cm)}) ---")
        for c in cm[:5]:
            print(f"  [{c['created_at'][:10]}] @{c['user']['login']}: {c['body'][:300]}")
