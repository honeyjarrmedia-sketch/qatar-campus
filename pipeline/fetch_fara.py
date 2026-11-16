"""Download the four DOJ FARA bulk files exactly as published.

The zips are stored untouched under raw/fara/ with a SHA-256 and the time of
retrieval, so any later number can be traced to a specific download.
"""
from . import config
from .common import http_get, now_utc, sha256_file, update_manifest


def run() -> list:
    out_dir = config.RAW / "fara"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for key, url in config.FARA_BULK.items():
        path = out_dir / url.rsplit("/", 1)[-1]
        entry = {"key": key, "url": url,
                 "path": str(path.relative_to(config.ROOT)),
                 "retrieved_at": now_utc()}
        try:
            data = http_get(url, timeout=300)
            if not data.startswith(b"PK"):
                raise RuntimeError(
                    "response is not a zip file (first bytes: %r)" % data[:40])
            path.write_bytes(data)
            entry.update(status="ok", bytes=len(data),
                         sha256=sha256_file(path))
        except Exception as e:  # recorded, never papered over
            entry.update(status="error", error=str(e)[:500])
        print(f"[fara] {key}: {entry['status']}")
        entries.append(entry)
    update_manifest("fara", entries)
    return entries


if __name__ == "__main__":
    run()
