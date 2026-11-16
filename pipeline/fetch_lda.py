"""Download LDA filings linked to each featured country from lda.gov.

For every featured country code and every filter in config.LDA_FILTERS the
script pages through the official API and stores each filing's JSON exactly
as returned, one per line, in raw/lda/<CC>/<filter>.jsonl.gz.

Safety checks, because an API silently ignoring an unknown filter would
return the whole two-million-filing database:
  1. The filtered count must be far below the unfiltered count.
  2. Every filing on the first page must actually satisfy the filter when
     checked locally.
A filter failing either check is skipped and recorded in the manifest.
"""
import gzip
import json
import os
import time
import urllib.error
import urllib.parse

from . import config
from .common import http_get, now_utc, sha256_file, update_manifest


def _headers() -> dict:
    key = os.environ.get("LDA_API_KEY", "").strip()
    h = {"Accept": "application/json"}
    if key:
        h["Authorization"] = f"Token {key}"
    return h


def _sleep() -> None:
    has_key = bool(os.environ.get("LDA_API_KEY", "").strip())
    time.sleep(config.LDA_SLEEP_WITH_KEY if has_key else config.LDA_SLEEP_ANON)


def _get_json(url: str) -> dict:
    return json.loads(http_get(url, headers=_headers(), timeout=120))


def filing_matches(filing: dict, flt: str, cc: str) -> bool:
    """Local re-check that a filing really satisfies the API filter."""
    client = filing.get("client") or {}
    fes = filing.get("foreign_entities") or []
    aos = filing.get("affiliated_organizations") or []
    if flt == "client_country":
        return client.get("country") == cc
    if flt == "client_ppb_country":
        return client.get("ppb_country") == cc
    if flt == "foreign_entity_country":
        return any(e.get("country") == cc for e in fes)
    if flt == "foreign_entity_ppb_country":
        return any(e.get("ppb_country") == cc for e in fes)
    if flt == "affiliated_organization_country":
        return any(e.get("country") == cc for e in aos)
    if flt == "affiliated_organization_ppb_country":
        return any(e.get("ppb_country") == cc for e in aos)
    return False


def _fetch_one(flt: str, cc: str, baseline: int, out_path) -> dict:
    params = {flt: cc, "page_size": config.LDA_PAGE_SIZE, "ordering": "dt_posted"}
    url = config.LDA_API + "?" + urllib.parse.urlencode(params)
    entry = {"filter": flt, "country_code": cc, "url": url,
             "retrieved_at": now_utc()}
    try:
        try:
            page = _get_json(url)
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # "ordering" rejected: retry without it.
            params.pop("ordering")
            url = config.LDA_API + "?" + urllib.parse.urlencode(params)
            entry["url"] = url
            page = _get_json(url)
        count = page.get("count", 0)
        entry["api_count"] = count
        if baseline and count > baseline * 0.2:
            entry.update(status="skipped",
                         note="filter appears to be ignored by the API "
                              f"(count {count} vs {baseline} unfiltered)")
            return entry
        first = page.get("results") or []
        bad = [f.get("filing_uuid") for f in first
               if not filing_matches(f, flt, cc)]
        if bad:
            entry.update(status="skipped",
                         note="first page contains filings that do not "
                              "satisfy the filter locally",
                         examples=bad[:5])
            return entry

        saved = 0
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0 keeps the gzip byte-identical when the content is.
        with open(out_path, "wb") as raw_f, \
                gzip.GzipFile(fileobj=raw_f, mode="wb", mtime=0) as gz:
            while True:
                for filing in page.get("results") or []:
                    gz.write((json.dumps(filing, ensure_ascii=False,
                                         sort_keys=True) + "\n").encode("utf-8"))
                    saved += 1
                nxt = page.get("next")
                if not nxt:
                    break
                _sleep()
                page = _get_json(nxt)
        entry.update(status="ok", saved=saved,
                     path=str(out_path.relative_to(config.ROOT)),
                     sha256=sha256_file(out_path))
        if saved != count:
            entry["note"] = (f"API reported {count} filings but {saved} were "
                             "saved; new filings may have posted mid-download")
    except Exception as e:
        entry.update(status="error", error=str(e)[:500])
    return entry


def run() -> list:
    entries = []
    try:
        baseline = _get_json(config.LDA_API + "?page_size=1").get("count", 0)
    except Exception as e:
        entries.append({"status": "error",
                        "error": f"baseline count failed: {e}"[:500],
                        "retrieved_at": now_utc()})
        update_manifest("lda", entries)
        print("[lda] baseline request failed:", e)
        return entries
    print(f"[lda] unfiltered filing count: {baseline}")
    for cc in config.FEATURED:
        for flt in config.LDA_FILTERS:
            _sleep()
            out_path = config.RAW / "lda" / cc / f"{flt}.jsonl.gz"
            entry = _fetch_one(flt, cc, baseline, out_path)
            print(f"[lda] {cc} {flt}: {entry['status']} "
                  f"(api_count={entry.get('api_count')}, "
                  f"saved={entry.get('saved')})")
            entries.append(entry)
            update_manifest("lda", [{"unfiltered_count": baseline}] + entries)
    return entries


if __name__ == "__main__":
    run()
