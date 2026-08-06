#!/usr/bin/env python3
"""Re-verify candidates #76255 #76196 #76254 #76243 against upstream (anonymous API)."""
import json, time, urllib.request, urllib.error

BASE = "https://api.github.com/repos/NousResearch/hermes-agent"
HDRS = {"User-Agent": "task001-cron", "Accept": "application/vnd.github+json"}

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.code, "msg": e.read().decode()[:300]}, e.code

rl, _ = get("https://api.github.com/rate_limit")
core = rl.get("resources", {}).get("core", {})
print("RATE core:", core.get("remaining"), "/", core.get("limit"))

for n in [76255, 76196, 76254, 76243]:
    print("=" * 70)
    issue, st = get(f"{BASE}/issues/{n}")
    if st != 200:
        print(f"#{n} ERROR {st}: {issue.get('msg', issue)}")
        continue
    assignees = ", ".join(a["login"] for a in issue.get("assignees", [])) or "无"
    labels = ", ".join(l["name"] for l in issue.get("labels", [])) or "无标签"
    print(f"#{n} [{issue['state']}] {issue['title']}")
    print(f"  created={issue['created_at']} updated={issue['updated_at']} comments={issue['comments']} assignees={assignees}")
    print(f"  labels: {labels}")
    if issue.get("pull_request"):
        print("  !! is a PULL REQUEST, skip")
        continue
    tl, st2 = get(f"{BASE}/issues/{n}/timeline?per_page=100")
    if st2 == 200:
        refs = []
        for ev in tl:
            if ev.get("event") == "cross-referenced":
                src = ev["source"]["issue"]
                refs.append((src["number"], src["title"][:70], "PR" if "pull_request" in src else "issue"))
        if refs:
            for rn, rt, rk in refs:
                if rk == "PR":
                    pr, st3 = get(f"{BASE}/pulls/{rn}")
                    if st3 == 200:
                        print(f"  cross-ref -> {rk} #{rn} [{pr['state']}] merged={pr.get('merged')} draft={pr.get('draft')} by={pr['user']['login']}: {rt}")
                    else:
                        print(f"  cross-ref -> {rk} #{rn}: {rt} (PR fetch err {st3})")
                else:
                    print(f"  cross-ref -> {rk} #{rn}: {rt}")
        else:
            print("  cross-ref: 无")
    else:
        print(f"  timeline ERR {st2}")
    cm, st4 = get(f"{BASE}/issues/{n}/comments?per_page=10")
    if st4 == 200 and cm:
        print(f"  latest comments ({len(cm)}):")
        for c in cm[:4]:
            body = c["body"].replace("\n", " ")[:150]
            print(f"    [{c['created_at'][:16]}] @{c['user']['login']}: {body}")
    else:
        print("  comments: 无")
    time.sleep(1)
