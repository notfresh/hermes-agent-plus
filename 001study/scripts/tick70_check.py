#!/usr/bin/env python3
"""任务001 例行候选池复查脚本（tick 70）
批量核查：详情(updated/comments/assignees) + timeline cross-ref + 增量扫描
"""
import os, json, urllib.request, sys, time

token = None
env_path = os.path.expanduser("~/.hermes/.env")
if os.path.exists(env_path):
    for line in open(env_path):
        if line.startswith("GITHUB_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break

def api(url):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read().decode()[:200]}
    except Exception as e:
        return {"_error": str(e)}

def check_issue(num):
    """核查三件事：详情 / 评论 / timeline cross-ref"""
    out = {"num": num}
    d = api(f"https://api.github.com/repos/NousResearch/hermes-agent/issues/{num}")
    if "_error" in d:
        out["error"] = d["_error"]
        return out
    out["state"] = d["state"]
    out["title"] = d["title"][:90]
    out["updated"] = d["updated_at"]
    out["created"] = d["created_at"]
    out["comments"] = d["comments"]
    out["assignees"] = [a["login"] for a in d.get("assignees", [])]
    out["labels"] = [l["name"] for l in d.get("labels", [])]
    # timeline cross-ref
    tl = api(f"https://api.github.com/repos/NousResearch/hermes-agent/issues/{num}/timeline?per_page=100")
    if isinstance(tl, list):
        refs = []
        for ev in tl:
            if ev.get("event") == "cross-referenced":
                src = ev["source"]["issue"]
                t = "PR" if "pull_request" in src else "issue"
                refs.append(f"{t}#{src['number']}:{src['title'][:50]}")
            elif ev.get("event") in ("closed", "labeled", "assigned"):
                refs.append(f"{ev['event']}")
        out["timeline"] = refs[:8]
    else:
        out["timeline"] = [f"err:{tl.get('_error','?')}"]
    return out

def check_pr_state(num):
    d = api(f"https://api.github.com/repos/NousResearch/hermes-agent/pulls/{num}")
    if "_error" in d:
        return f"PR#{num} err"
    return f"PR#{num} [{d['state']}] merged={d['merged']} draft={d.get('draft')} author={d['user']['login']}"

def incr_scan(since):
    """增量扫描：since 之后创建的 issue"""
    q = f"repo:NousResearch/hermes-agent created:>{since} is:issue"
    import urllib.parse
    url = "https://api.github.com/search/issues?q=" + urllib.parse.quote(q) + "&sort=created&order=asc&per_page=50"
    d = api(url)
    if "_error" in d or "items" not in d:
        return [f"search err: {d.get('_error')}"]
    items = []
    for i in d["items"]:
        if "pull_request" in i:
            continue
        items.append({
            "num": i["number"],
            "title": i["title"][:80],
            "created": i["created_at"],
            "labels": [l["name"] for l in i.get("labels", [])][:5],
            "comments": i["comments"],
            "state": i["state"],
        })
    return items

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "candidates":
        nums = [int(x) for x in sys.argv[2].split(",")]
        results = []
        for n in nums:
            r = check_issue(n)
            results.append(r)
            print(f"#{r['num']} [{r.get('state','?')}] upd={r.get('updated','?')[:16]} comm={r.get('comments','?')} asg={r.get('assignees') or '无'}")
            print(f"   title: {r.get('title','?')}")
            if r.get("timeline"):
                print(f"   timeline: {r['timeline']}")
            time.sleep(0.4)
        json.dump(results, open("/tmp/task001-cand-check.json", "w"), ensure_ascii=False, indent=1)
    elif mode == "scan":
        since = sys.argv[2]
        items = incr_scan(since)
        print(f"增量扫描 {since} 之后共 {len(items)} 条新 issue:")
        for i in items:
            print(f"  #{i['num']} [{i['state']}] {i['created'][:16]} {','.join(i['labels'])[:40]:42} {i['title']}")
        json.dump(items, open("/tmp/task001-incr-scan.json", "w"), ensure_ascii=False, indent=1)
