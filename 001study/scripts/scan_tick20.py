#!/usr/bin/env python3
"""Task001 tick20: 复查 #77211/#77173 + 扫新 issue 池（good first issue / help wanted / easy）"""
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

def check_issue(num):
    print(f"\n===== 复查 #{num} =====")
    i = api(f"/repos/NousResearch/hermes-agent/issues/{num}")
    if "__err__" in i:
        print(f"ERR: {i['__err__']}"); return
    assignees = ', '.join(a['login'] for a in i['assignees']) or '无'
    print(f"[{i['state']}] #{i['number']} {i['title'][:70]}")
    print(f"  labels: {', '.join(l['name'] for l in i['labels'])[:100]}")
    print(f"  assignees: {assignees} | comments: {i['comments']} | updated: {i['updated_at']}")
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
    else:
        print(f"  timeline err: {str(tl)[:80]}")
    cs = api(f"/repos/NousResearch/hermes-agent/issues/{num}/comments?per_page=3")
    if isinstance(cs, list) and cs:
        for c in cs[-2:]:
            print(f"  comment [{c['created_at'][:10]}] @{c['user']['login']}: {c['body'][:120].replace(chr(10),' ')}")
    time.sleep(0.3)

check_issue(77211)
check_issue(77173)

print("\n\n########## 新 issue 池扫描 ##########")
seen = set()
for label in ["good first issue", "help wanted", "easy"]:
    q = f'repo:NousResearch/hermes-agent is:issue is:open label:"{label}"'
    url = "/search/issues?q=" + urllib.parse.quote(q) + "&sort=created&order=desc&per_page=10"
    d = api(url)
    if "__err__" in d or 'items' not in d:
        print(f"label={label} ERR: {d.get('__err__', str(d)[:80])}")
        continue
    print(f"\n--- label={label}: total={d.get('total_count','?')} open ---")
    for it in d['items']:
        if it['number'] in seen: continue
        seen.add(it['number'])
        labs = ', '.join(l['name'] for l in it['labels'])[:70]
        print(f"  #{it['number']} [{it['created_at'][:10]}] {it['title'][:65]}")
        print(f"      labels: {labs}")
    time.sleep(0.3)
