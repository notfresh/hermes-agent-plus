#!/usr/bin/env python3
"""Claim check for candidate issues (tick #16, silent window 2026-08-02 00:xx).
Uses anonymous GitHub API (core limit 60/h). Prints compact per-issue report."""
import json, sys, time, urllib.request

REPO = "NousResearch/hermes-agent"
BASE = f"https://api.github.com/repos/{REPO}"
candidates = [int(x) for x in sys.argv[1:]]

def get(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "task001-cron",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

for n in candidates:
    print("=" * 100)
    try:
        i = get(f"{BASE}/issues/{n}")
    except Exception as e:
        print(f"#{n} ERROR: {e}")
        continue
    assignees = ", ".join(a["login"] for a in i.get("assignees", [])) or "无"
    labels = ", ".join(l["name"] for l in i["labels"]) or "(无标签)"
    print(f"#{i['number']} [{i['state']}] {i['title']}")
    print(f"  created={i['created_at']}  updated={i['updated_at']}  comments={i['comments']}  assignees={assignees}")
    print(f"  labels: {labels}")
    body = (i.get("body") or "").strip().replace("\n", " ")
    print(f"  body: {body[:450]}")
    # comments (latest 3)
    try:
        cs = get(f"{BASE}/issues/{n}/comments?per_page=3")
        for c in cs:
            print(f"  [comment {c['created_at'][:16]}] @{c['user']['login']}: {c['body'][:220].replace(chr(10),' ')}")
    except Exception as e:
        print(f"  comments ERROR: {e}")
    # timeline cross-references
    try:
        tl = get(f"{BASE}/issues/{n}/timeline?per_page=100")
        for ev in tl:
            if ev.get("event") == "cross-referenced":
                src = ev["source"]["issue"]
                kind = "PR" if "pull_request" in src else "issue"
                print(f"  cross-ref -> {kind} #{src['number']}: {src['title'][:90]} (state={src.get('state')})")
    except Exception as e:
        print(f"  timeline ERROR: {e}")
    time.sleep(0.3)
print("=" * 100)
print("DONE")
