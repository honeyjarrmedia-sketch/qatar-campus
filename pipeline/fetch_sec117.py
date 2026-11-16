"""Download the Department of Education Section 117 spreadsheet(s) and
report their real structure.

No cleaning happens here. The column layout is written to
data/reports/sec117_structure.json so the cleaner can be written against
what the file actually contains instead of an assumed layout.
"""
from . import config
from .common import http_get, now_utc, sha256_file, update_manifest, write_json


def inspect(path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        head = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 8:
                break
            head.append([None if c is None else str(c)[:80] for c in row])
        sheets.append({"name": ws.title, "max_row": ws.max_row,
                       "max_column": ws.max_column, "first_rows": head})
    return {"sheets": sheets}


def run() -> list:
    out_dir = config.RAW / "sec117"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries, structure = [], {}
    for key, url in config.SEC117_FILES.items():
        path = out_dir / url.rsplit("/", 1)[-1]
        entry = {"key": key, "url": url,
                 "path": str(path.relative_to(config.ROOT)),
                 "retrieved_at": now_utc()}
        try:
            data = http_get(url, timeout=600)
            if not data.startswith(b"PK"):
                raise RuntimeError(
                    "response is not an xlsx file (first bytes: %r)" % data[:40])
            path.write_bytes(data)
            entry.update(status="ok", bytes=len(data), sha256=sha256_file(path))
            # Only the header rows are recorded, never full records.
            info = inspect(path)
            for s in info["sheets"]:
                s["first_rows"] = s["first_rows"][:3]
            structure[key] = info
        except Exception as e:
            entry.update(status="error", error=str(e)[:500])
        print(f"[sec117] {key}: {entry['status']}")
        entries.append(entry)
    update_manifest("sec117", entries)
    write_json(config.REPORTS / "sec117_structure.json", structure)
    return entries


if __name__ == "__main__":
    run()
