#!/usr/bin/env python3
"""Task001 tick25: 快速核查 #78148 / #78144（附带回）"""
import urllib.request, json, time

def api(path):
    req = urllib.request.Request(f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "task001-issue-scanner")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception as e:
        return {"__err__": str(e)}

for num in [78148, 78144]:
    print(f"\n===== #{num} =====")
    i = api(f"/repos/NousResearch/hermes-agent/issues/{num}")
    if "__err__" in i:
        print(f"ERR: {i['__err__']}"); continue
    assignees = ', '.join(a['login'] for a in i['assignees']) or '无'
    print(f"[{i['state']}] {i['title'][:80]}")
    print(f"  labels: {', '.join(l['name'] for l in i['labels'])[:100]}")
    print(f"  assignees: {assignees} | comments: {i['comments']} | updated: {i['updated_at']}")
    body = (i.get('body') or '')[:400].replace('\n', ' ')
    print(f"  body: {body}")
    tl = api(f"/repos/NousResearch/hermes-agent/issues/{num}/timeline?per_page=100")
    if isinstance(tl, list):
        refs = [ev for ev in tl if ev.get('event') == 'cross-referenced']
        if refs:
            for ev in refs:
                src = ev['source']['issue']
                t = 'PR' if 'pull_request' in src else 'issue'
                print(f"  cross-ref -> {t} #{src['number']}: {src['title'][:60]} (state={src.get('state')})")
        else:
            print("  无 cross-ref")
    cs = api(f"/repos/NousResearch/hermes-agent/issues/{num}/comments?per_page=3")
    if isinstance(cs, list) and cs:
        for c in cs[-2:]:
            print(f"  comment [{c['created_at'][:10]}] @{c['user']['login']}: {c['body'][:150].replace(chr(10),' ')}")
    time.sleep(0.4)
