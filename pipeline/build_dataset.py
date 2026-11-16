"""Merge the cleaned sources into the published dataset and validate it.

Outputs (data/clean/):
  records.json.gz / records.csv.gz  one record per line, gzipped
  entities.json                one entry per registrant
  connections.json             registrants with records in 2+ featured countries
  fara_documents.json          DOJ document links for featured FARA registrants
  summary.json                 row counts, used for review and the site

The build fails if any record lacks a source link on an official host.
"""
import csv
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

from . import clean_fara, clean_lda, clean_sec117, config
from .common import norm_name, now_utc, read_json, write_json, write_json_rows, write_records

# The fourteen columns from the project brief come first, in its order.
CSV_COLUMNS = [
    "id", "country", "actor_type", "entity_or_person_name", "role",
    "foreign_principal", "amount_usd", "year", "purpose", "source_url",
    "source_type", "confidence", "date_retrieved", "notes",
    # Additions that keep each row traceable and unambiguous.
    "country_code", "country_as_filed", "featured", "entity_id", "client_name",
    "amount_type", "year_end", "date_start", "date_end", "period",
    "purpose_detail", "lobbyists", "source_urls", "source_record_id",
    "link_basis", "superseded",
]
REQUIRED = ["id", "country", "actor_type", "entity_or_person_name", "role",
            "source_url", "source_type", "confidence", "date_retrieved"]
CONFIDENCE = {"verified", "derived", "partial"}


def validate(records: list) -> list:
    errors, seen = [], set()
    for r in records:
        rid = r.get("id")
        if rid in seen:
            errors.append({"id": rid, "error": "duplicate id"})
        seen.add(rid)
        for field in REQUIRED:
            if r.get(field) in (None, ""):
                errors.append({"id": rid, "error": f"missing {field}"})
        if r.get("confidence") not in CONFIDENCE:
            errors.append({"id": rid, "error": "invalid confidence flag"})
        for url in [r.get("source_url")] + list(r.get("source_urls") or []):
            if not url:
                continue
            p = urlparse(url)
            if p.scheme != "https" or p.hostname not in config.ALLOWED_SOURCE_HOSTS:
                errors.append({"id": rid, "error": f"source link not on an official host: {url}"})
    return errors


def build_connections(records: list, entities: dict) -> list:
    by_entity = defaultdict(lambda: defaultdict(list))
    all_countries = defaultdict(set)
    all_principals = defaultdict(set)
    for r in records:
        all_countries[r["entity_id"]].add(r["country"])
        if r["foreign_principal"]:
            all_principals[r["entity_id"]].add(r["foreign_principal"])
        if r["featured"]:
            by_entity[r["entity_id"]][r["country_code"]].append({
                "record_id": r["id"],
                "foreign_principal": r["foreign_principal"],
                "year": r["year"],
                "source_url": r["source_url"],
            })
    out = []
    for eid, per_country in by_entity.items():
        if len(per_country) < 2:
            continue
        ent = entities.get(eid, {})
        is_fara = eid.startswith("fara-")
        out.append({
            "entity_id": eid,
            "name": ent.get("name", ""),
            "source": ent.get("source", ""),
            "featured_countries": sorted(per_country),
            "records_by_country": {cc: per_country[cc] for cc in sorted(per_country)},
            # Context: how many countries this registrant or institution has
            # records for in the whole source file. Known for FARA and for
            # Section 117; not known for LDA, which is downloaded per country.
            "all_countries_in_dataset": (len(all_countries[eid]) if is_fara
                                         else ent.get("countries_in_source")),
            "all_foreign_principals_in_dataset": len(all_principals[eid]) if is_fara else None,
            "confidence": "derived",
            "method": "Same FARA registration number, LDA registrant ID or "
                      "Department of Education institution ID has records "
                      "for two or more featured "
                      "countries. Overlap only; no relationship between the "
                      "countries is stated or implied.",
        })
    out.sort(key=lambda c: (-len(c["featured_countries"]), c["name"]))
    return out


def run() -> int:
    sources, records, entities, documents = {}, [], {}, {}
    for name, module in (("fara", clean_fara), ("lda", clean_lda), ("sec117", clean_sec117)):
        try:
            res = module.run()
        except Exception as e:
            sources[name] = {"included": False, "error": str(e)[:2000]}
            print(f"[build] {name} NOT included: {e}", file=sys.stderr)
            continue
        sources[name] = {"included": True, "records": len(res["records"])}
        records.extend(res["records"])
        entities.update({e["entity_id"]: e for e in res["entities"]})
        documents.update(res.get("documents", {}))

    # Fee lines read from supplemental statements by pipeline.extract_fara_fees.
    # They are produced from records.json, so they are merged here on the next
    # clean rather than being rebuilt in this step.
    for path in sorted(config.CLEAN.glob("fara_fees_*.json")):
        fees = read_json(path, []) or []
        if fees:
            sources[f"fara_fees_{path.stem.split('_')[-1]}"] = {"included": True, "records": len(fees)}
            records.extend(fees)
            print(f"[build] merged {len(fees)} fee lines from {path.name}")

    for r in records:
        r.setdefault("purpose_detail", "")
        r.setdefault("lobbyists", [])

    # Links the checker found dead: the document has gone from the
    # government site since it was indexed. The record stays, but it is
    # marked partial and points at the list of everything filed under that
    # registration, which is the nearest thing that still opens.
    dead = {d["url"] for d in (read_json(config.REPORTS / "link_check.json", {}) or {}).get("dead", [])
            if d.get("status") == 404}
    swapped = []
    for r in records:
        if not dead or r["source_url"] not in dead:
            continue
        gone = r["source_url"]
        listing = (config.FARA_DOC_LISTING.format(regnum=r["source_record_id"])
                   if r["actor_type"] in ("fara_registrant", "fara_fee") else "")
        if not listing:
            continue
        r["source_url"] = listing
        r["source_urls"] = [u for u in r["source_urls"] if u != gone] or [listing]
        r["source_type"] = "FARA document listing"
        r["confidence"] = "partial"
        r["notes"] = (r["notes"] + " " if r["notes"] else "") + (
            f"The exhibit this row was indexed from ({gone}) no longer opens on the "
            "Justice Department site. The link above lists every document filed "
            "under this registration.")
        swapped.append({"id": r["id"], "was": gone, "now": listing})
    if swapped:
        write_json(config.REPORTS / "dead_links_swapped.json", swapped)
        print(f"[build] {len(swapped)} record(s) repointed from a dead document link")

    errors = validate(records)
    write_json(config.REPORTS / "validation_errors.json", errors)

    connections = build_connections(records, entities)

    # Same name under FARA and LDA. Reported for human review only: a shared
    # name is not proof of a shared organisation, so nothing is merged.
    by_name = defaultdict(set)
    for e in entities.values():
        by_name[norm_name(e["name"])].add(e["entity_id"])
    possible = [{"normalised_name": n, "entity_ids": sorted(ids)}
                for n, ids in sorted(by_name.items())
                if n and len({i.split("-")[0] for i in ids}) > 1]
    write_json(config.REPORTS / "possible_same_entity.json", possible)

    config.CLEAN.mkdir(parents=True, exist_ok=True)
    write_records(config.CLEAN / "records.json.gz", records)
    write_json(config.CLEAN / "entities.json",
               sorted(entities.values(), key=lambda e: e["name"].upper()))
    write_json_rows(config.CLEAN / "connections.json", connections)
    write_json_rows(config.CLEAN / "fara_documents.json",
                    [{"registration_number": k, "documents": v} for k, v in documents.items()])
    import gzip as _gzip
    import io as _io
    with open(config.CLEAN / "records.csv.gz", "wb") as _raw, \
            _gzip.GzipFile(fileobj=_raw, mode="wb", compresslevel=6, mtime=0) as _gz, \
            _io.TextIOWrapper(_gz, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = dict(r)
            for k in ("lobbyists", "source_urls"):
                row[k] = " | ".join(row.get(k) or [])
            row["amount_usd"] = "" if r["amount_usd"] is None else f"{r['amount_usd']:.2f}"
            w.writerow(row)

    years = [r["year"] for r in records if r.get("year")]
    by_source_country = defaultdict(Counter)
    for r in records:
        if r["featured"]:
            by_source_country[r["id"].split("-")[0]][r["country"]] += 1
    summary = {
        "generated_at": now_utc(),
        "sources": sources,
        "records_total": len(records),
        "records_featured": sum(r["featured"] for r in records),
        "featured_records_by_source_and_country": {k: dict(v) for k, v in by_source_country.items()},
        "records_by_confidence": dict(Counter(r["confidence"] for r in records)),
        "records_with_amount": sum(r["amount_usd"] is not None for r in records),
        "entities": len(entities),
        "connections": len(connections),
        "year_range": [min(years), max(years)] if years else None,
        "validation_errors": len(errors),
    }
    write_json(config.CLEAN / "summary.json", summary)
    print("[build] records:", len(records), "| entities:", len(entities),
          "| connections:", len(connections), "| validation errors:", len(errors))
    if errors:
        print("[build] FAILED validation; see data/reports/validation_errors.json",
              file=sys.stderr)
        return 1
    if not all(s["included"] for s in sources.values()):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(run())
