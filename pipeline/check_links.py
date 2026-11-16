"""Check every source link in the dataset and report dead ones.

Results are cached per URL so a quarterly run only re-checks links that
were last checked more than MAX_AGE_DAYS ago or that failed last time.

Output: data/reports/link_check.json with totals and, for every link that
did not return a normal page, the records that depend on it.
"""
import datetime as dt
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

from . import config
from .common import now_utc, read_json, write_json

MAX_AGE_DAYS = 80
DELAY_SECONDS = 0.35


def check(url: str) -> dict:
    """Return {"status": int or None, "ok": bool, "error": str}."""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method,
                headers={"User-Agent": config.USER_AGENT, "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return {"status": resp.status, "ok": resp.status in (200, 206), "error": ""}
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue  # server refuses HEAD; try GET
            return {"status": e.code, "ok": False, "error": str(e.reason)[:200]}
        except Exception as e:
            if method == "HEAD":
                continue
            return {"status": None, "ok": False, "error": str(e)[:200]}
    return {"status": None, "ok": False, "error": "no response"}


def run(limit: int | None = None, max_minutes: float | None = None) -> int:
    records = read_json(config.CLEAN / "records.json", [])
    if not records:
        print("[links] no records to check", file=sys.stderr)
        return 1
    users = defaultdict(list)
    missing = []
    featured_urls = set()
    for r in records:
        if r.get("featured"):
            featured_urls.update(u for u in [r.get("source_url")] + list(r.get("source_urls") or []) if u)
        if not r.get("source_url"):
            missing.append(r["id"])
        for url in set([r.get("source_url")] + list(r.get("source_urls") or [])):
            if url:
                users[url].append(r["id"])

    cache_path = config.REPORTS / "link_check_cache.json"
    cache = read_json(cache_path, {}) or {}
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    todo = [u for u in sorted(users)
            if u not in cache or not cache[u]["ok"] or cache[u]["checked_at"] < cutoff]
    # Links behind featured-country records are checked first.
    todo.sort(key=lambda u: (u not in featured_urls, u))
    if limit:
        todo = todo[:limit]
    deadline = time.time() + max_minutes * 60 if max_minutes else None
    print(f"[links] {len(users)} distinct links, checking {len(todo)}")
    for i, url in enumerate(todo, 1):
        result = check(url)
        result["checked_at"] = now_utc()
        cache[url] = result
        if i % 200 == 0:
            write_json(cache_path, cache)
            print(f"[links] {i}/{len(todo)}")
        if deadline and time.time() > deadline:
            print(f"[links] time budget reached after {i} links")
            break
        time.sleep(DELAY_SECONDS)
    write_json(cache_path, cache)

    dead = [{"url": u, "status": cache[u]["status"], "error": cache[u]["error"],
             "checked_at": cache[u]["checked_at"], "record_ids": users[u][:50],
             "records_affected": len(users[u])}
            for u in sorted(users) if u in cache and not cache[u]["ok"]]
    unchecked = [u for u in users if u not in cache]
    report = {
        "generated_at": now_utc(),
        "records": len(records),
        "distinct_links": len(users),
        "links_ok": sum(1 for u in users if u in cache and cache[u]["ok"]),
        "links_dead_or_unreachable": len(dead),
        "links_not_yet_checked": len(unchecked),
        "featured_links_not_yet_checked": sum(1 for u in unchecked if u in featured_urls),
        "records_missing_source_url": missing,
        "dead": dead,
    }
    write_json(config.REPORTS / "link_check.json", report)
    print(f"[links] ok={report['links_ok']} dead={len(dead)} "
          f"unchecked={len(unchecked)} missing={len(missing)}")
    return 1 if (dead or missing) else 0


if __name__ == "__main__":
    sys.exit(run())
