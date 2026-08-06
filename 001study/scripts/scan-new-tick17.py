#!/usr/bin/env python3
"""Stage 1: scan new issues created after last scan point (2026-08-01T16:20:00Z)."""
import json, time, urllib.request, urllib.error

HDRS = {"User-Agent": "task001-cron", "Accept": "application/vnd.github+json"}

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.code, "msg": e.read().decode()[:300]}, e.code

# All new issues (not PRs) since last scan
q = "repo:NousResearch/hermes-agent created:>2026-08-01T16:20:00Z type:issue -is:pr"
url = f"https://api.github.com/search/issues?q={urllib.parse.quote(q)}&sort=created&order=asc&per_page=100"
import urllib.parse
data, st = get(url)
if st != 200:
    print("SEARCH ERR", st, data)
    raise SystemExit
items = data.get("items", [])
print(f"total new issues since 16:20Z: {data.get('total_count')} (fetched {len(items)})")
print()
for i in items:
    labels = ", ".join(l["name"] for l in i.get("labels", [])) or "-"
    print(f"#{i['number']:6} [{i['created_at'][11:16]}Z] {labels:55} {i['title'][:90]}")
