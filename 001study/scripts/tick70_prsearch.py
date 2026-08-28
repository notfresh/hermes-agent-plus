#!/usr/bin/env python3
"""用 search API 查候选 issue 的关联 PR（撞车核查备用通道）"""
import json, urllib.request, urllib.parse, sys

def api(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"_error": str(e)}

nums = [int(x) for x in sys.argv[1].split(",")]
q = "repo:NousResearch/hermes-agent (" + " OR ".join(str(n) for n in nums) + ") type:pr"
url = "https://api.github.com/search/issues?q=" + urllib.parse.quote(q) + "&sort=created&order=asc&per_page=50"
d = api(url)
if "_error" in d or "items" not in d:
    print("err:", d.get("_error") or d)
    sys.exit(1)
print(f"total: {d['total_count']}")
for i in d["items"]:
    body = i.get("body") or ""
    mentioned = [n for n in nums if str(n) in body or str(n) in i.get("title", "")]
    print(f"PR #{i['number']} [{i['state']}] {i['created_at'][:16]} 提及 {mentioned}  {i['title'][:70]}")
