"""Download FARA supplemental statements for one country's registrations.

These PDFs hold the fee figures that the bulk data leaves out (Item 14(a)).
They are downloaded to raw/fara_docs/<regnum>/ and never altered.

  python -m pipeline.fetch_fara_docs --country QA [--since 2015] [--sample 8]

--sample downloads only the newest N statements and writes their extracted
text to data/reports/fara_doc_text_sample.txt, so the layout can be read
before an extractor is written against it.
"""
import argparse
import subprocess
import sys

from . import config
from .common import http_get, now_utc, read_json, sha256_file, update_manifest, write_json


def statements_for(country_code: str, since: str) -> list:
    """Supplemental statements filed under registrations that have a record
    for this country, newest first."""
    records = [__import__("json").loads(line.rstrip(",\n"))
               for line in open(config.CLEAN / "records.json", encoding="utf-8")
               if line.strip() not in "[]"]
    regs = {r["source_record_id"] for r in records
            if r["country_code"] == country_code and r["actor_type"] == "fara_registrant"}
    docs = read_json(config.CLEAN / "fara_documents.json", []) or []
    out = []
    for entry in docs:
        if entry["registration_number"] not in regs:
            continue
        for d in entry["documents"]:
            if "supplemental" in d["type"].lower() and (d["date"] or "") >= since:
                out.append({"regnum": entry["registration_number"], "date": d["date"],
                            "url": d["url"]})
    out.sort(key=lambda d: (d["date"] or "", d["url"]), reverse=True)
    return out


def pdf_text(path) -> str:
    """Text layer only. A scan with no text layer returns an empty string:
    nothing is guessed from the image."""
    try:
        done = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                              capture_output=True, timeout=120)
        return done.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def run(country_code: str, since: str, sample: int | None) -> int:
    wanted = statements_for(country_code, since)
    if sample:
        wanted = wanted[:sample]
    print(f"[docs] {len(wanted)} supplemental statements for {country_code} since {since}")
    entries, texts = [], []
    for i, doc in enumerate(wanted, 1):
        out_dir = config.RAW / "fara_docs" / doc["regnum"]
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / doc["url"].rsplit("/", 1)[-1]
        entry = {"regnum": doc["regnum"], "date": doc["date"], "url": doc["url"],
                 "path": str(path.relative_to(config.ROOT)), "retrieved_at": now_utc()}
        if path.exists() and path.stat().st_size > 0:
            entry.update(status="cached", bytes=path.stat().st_size, sha256=sha256_file(path))
        else:
            try:
                data = http_get(doc["url"], timeout=180)
                if not data.startswith(b"%PDF"):
                    raise RuntimeError("response is not a PDF (first bytes: %r)" % data[:30])
                path.write_bytes(data)
                entry.update(status="ok", bytes=len(data), sha256=sha256_file(path))
            except Exception as e:
                entry.update(status="error", error=str(e)[:400])
        if entry["status"] in ("ok", "cached"):
            text = pdf_text(path)
            entry["text_chars"] = len(text.strip())
            entry["has_text_layer"] = entry["text_chars"] > 200
            if sample:
                texts.append(f"\n\n{'=' * 78}\n{doc['url']}\nregistration {doc['regnum']} · "
                             f"filed {doc['date']} · {entry['text_chars']} characters of text\n"
                             f"{'=' * 78}\n{text[:14000]}")
        entries.append(entry)
        if i % 25 == 0:
            print(f"[docs] {i}/{len(wanted)}")
            update_manifest(f"fara_docs_{country_code}", entries)
    update_manifest(f"fara_docs_{country_code}", entries)
    ok = [e for e in entries if e["status"] in ("ok", "cached")]
    summary = {"country_code": country_code, "since": since, "requested": len(wanted),
               "downloaded": len(ok),
               "errors": [e for e in entries if e["status"] == "error"][:20],
               "with_text_layer": sum(1 for e in ok if e.get("has_text_layer")),
               "image_only_no_text": sum(1 for e in ok if not e.get("has_text_layer"))}
    write_json(config.REPORTS / f"fara_docs_{country_code}.json", summary)
    if sample:
        (config.REPORTS / "fara_doc_text_sample.txt").write_text("".join(texts), encoding="utf-8")
    print(f"[docs] downloaded {len(ok)} | with text layer "
          f"{summary['with_text_layer']} | image-only {summary['image_only_no_text']}")
    return 1 if len(ok) == 0 else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="QA")
    ap.add_argument("--since", default="2015-01-01")
    ap.add_argument("--sample", type=int, default=None)
    a = ap.parse_args()
    sys.exit(run(a.country, a.since, a.sample))
