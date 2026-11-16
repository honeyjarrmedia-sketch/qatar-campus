"""Turn the raw FARA bulk files into records.

One record per registrant / foreign-principal relationship, exactly as the
DOJ file lists it. Nothing is inferred: the bulk data carries no dollar
amounts, so amount_usd is always empty here.

If a file's columns are not the ones this code expects, the step stops and
prints the columns it found. It never guesses a column.
"""
import csv
import io
import zipfile
from collections import Counter, defaultdict

from . import config
from .common import (norm_header, norm_name, parse_mdy, read_json, short_hash,
                     slugify, title_country, write_json)

# Expected columns, as normalised header -> accepted spellings.
FP_COLS = {
    "principal": ["foreignprincipal"],
    "country": ["countrylocationrepresented"],
    "regnum": ["registrationnumber"],
    "registrant": ["registrantname"],
    "fp_start": ["foreignprincipalregistrationdate"],
}
FP_OPTIONAL = {"fp_end": ["foreignprincipalterminationdate"]}
REG_COLS = {
    "regnum": ["registrationnumber"],
    "name": ["name"],
    "reg_date": ["registrationdate"],
}
REG_OPTIONAL = {"term_date": ["terminationdate"],
                "business_name": ["businessname"],
                "city": ["city"], "state": ["state"]}
DOC_COLS = {
    "date": ["datestamped"],
    "regnum": ["registrationnumber"],
    "doc_type": ["documenttype"],
    "url": ["url"],
}
DOC_OPTIONAL = {"fp_name": ["foreignprincipalname"],
                "fp_country": ["foreignprincipalcountry"]}


class SchemaError(RuntimeError):
    pass


def read_bulk_zip(path):
    """Return (rows as dicts keyed by normalised header, malformed_count,
    original headers)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise SchemaError(f"{path}: expected one CSV inside, found {z.namelist()}")
        text = z.read(names[0]).decode(config.FARA_ENCODING)
    reader = csv.reader(io.StringIO(text, newline=""))
    headers = next(reader)
    keys = [norm_header(h) for h in headers]
    rows, malformed = [], 0
    for line in reader:
        if not line or not any(c.strip() for c in line):
            continue
        if len(line) != len(keys):
            malformed += 1  # stray comma or quote; skipped and counted
            continue
        rows.append(dict(zip(keys, (c.strip() for c in line))))
    return rows, malformed, headers


def resolve(headers, required, optional, label):
    keys = {norm_header(h) for h in headers}
    mapping, missing = {}, []
    for field, options in required.items():
        hit = next((o for o in options if o in keys), None)
        if hit is None:
            missing.append(f"{field} (looked for {options})")
        mapping[field] = hit
    for field, options in optional.items():
        mapping[field] = next((o for o in options if o in keys), None)
    if missing:
        raise SchemaError(
            f"FARA {label} file does not have the expected columns.\n"
            f"  Missing: {missing}\n  Columns found: {headers}")
    return mapping


def _featured_lookup():
    return {v.upper(): cc for cc, meta in config.FEATURED.items()
            for v in meta["fara_values"]}


def run() -> dict:
    manifest = {e["key"]: e for e in (read_json(config.MANIFEST, {}) or {}).get("fara", [])
                if e.get("status") == "ok"}
    needed = ["registrants", "foreign_principals", "registrant_docs"]
    missing = [k for k in needed if k not in manifest]
    if missing:
        raise SchemaError(f"FARA raw files not downloaded: {missing}")

    def load(key):
        return read_bulk_zip(config.ROOT / manifest[key]["path"])

    reg_rows, reg_bad, reg_h = load("registrants")
    fp_rows, fp_bad, fp_h = load("foreign_principals")
    doc_rows, doc_bad, doc_h = load("registrant_docs")
    R = resolve(reg_h, REG_COLS, REG_OPTIONAL, "registrants")
    F = resolve(fp_h, FP_COLS, FP_OPTIONAL, "foreign principals")
    D = resolve(doc_h, DOC_COLS, DOC_OPTIONAL, "registrant docs")

    def g(row, mapping, field):
        col = mapping.get(field)
        return row.get(col, "") if col else ""

    retrieved = manifest["foreign_principals"]["retrieved_at"][:10]

    registrants = {}
    for r in reg_rows:
        registrants[g(r, R, "regnum")] = r

    # Documents grouped by registration number.
    docs_by_reg = defaultdict(list)
    for d in doc_rows:
        url = g(d, D, "url")
        if not url.startswith("https://"):
            continue
        docs_by_reg[g(d, D, "regnum")].append({
            "date": parse_mdy(g(d, D, "date")),
            "type": g(d, D, "doc_type"),
            "fp_name": g(d, D, "fp_name"),
            "url": url,
        })

    featured = _featured_lookup()
    country_counts = Counter()
    records, bad_dates = [], 0
    seen_ids = Counter()
    for row in fp_rows:
        raw_country = g(row, F, "country")
        country_counts[raw_country] += 1
        cc = featured.get(raw_country.upper())
        if config.FARA_SCOPE == "featured" and not cc:
            continue
        regnum = g(row, F, "regnum")
        principal = g(row, F, "principal")
        start_raw, end_raw = g(row, F, "fp_start"), g(row, F, "fp_end")
        start, end = parse_mdy(start_raw), parse_mdy(end_raw)
        if (start_raw and not start) or (end_raw and not end):
            bad_dates += 1

        # Source document: an exhibit filed under this registration number
        # that names this foreign principal (exact normalised match only).
        target = norm_name(principal)
        exhibits = sorted(
            (d for d in docs_by_reg.get(regnum, [])
             if "exhibit" in d["type"].lower()
             and d["fp_name"] and norm_name(d["fp_name"]) == target),
            key=lambda d: (d["date"] or "9999", d["url"]))
        notes = ["FARA bulk data carries no dollar amounts; amounts appear "
                 "only in the registrant's supplemental statements."]
        if exhibits:
            source_url = exhibits[0]["url"]
            source_urls = [d["url"] for d in exhibits]
            confidence = "verified"
        else:
            source_url = config.FARA_DOC_LISTING.format(regnum=regnum)
            source_urls = [source_url]
            confidence = "partial"
            notes.append("No exhibit naming this foreign principal was found "
                         "in the DOJ document index; the link lists every "
                         "document filed under this registration number.")
        if not end:
            notes.append("No termination date in the DOJ file.")

        base_id = f"fara-{regnum}-{short_hash(principal + '|' + raw_country + '|' + (start or ''))}"
        seen_ids[base_id] += 1
        rec_id = base_id if seen_ids[base_id] == 1 else f"{base_id}-{seen_ids[base_id]}"

        records.append({
            "id": rec_id,
            "country": config.FEATURED[cc]["name"] if cc else title_country(raw_country),
            "country_code": cc or "",
            "country_as_filed": raw_country,
            "featured": bool(cc),
            "actor_type": "fara_registrant",
            "entity_or_person_name": g(row, F, "registrant"),
            "entity_id": f"fara-{regnum}",
            "role": "Registered under FARA as agent of the foreign principal",
            "foreign_principal": principal,
            "client_name": "",
            "amount_usd": None,
            "amount_type": "",
            "year": int(start[:4]) if start else None,
            "year_end": int(end[:4]) if end else None,
            "date_start": start,
            "date_end": end,
            "period": "",
            "purpose": "",
            "source_url": source_url,
            "source_urls": source_urls,
            "source_type": "FARA exhibit" if exhibits else "FARA document listing",
            "source_record_id": regnum,
            "link_basis": "Country/location represented, as listed in the DOJ FARA file",
            "confidence": confidence,
            "superseded": False,
            "date_retrieved": retrieved,
            "notes": " ".join(notes),
        })

    # A featured country with zero rows means the configured spelling is
    # wrong, not that the country has no registrants. Stop rather than
    # publish an empty country.
    found = {r["country_code"] for r in records if r["featured"]}
    absent = [cc for cc in config.FEATURED if cc not in found]
    review = [{"country_as_filed": c, "rows": n,
               "mapped_to": featured.get(c.upper(), "")}
              for c, n in sorted(country_counts.items())
              if any(f in c.upper() for f in config.FARA_REVIEW_FRAGMENTS)]
    write_json(config.REPORTS / "fara_country_review.json", review)
    if absent:
        raise SchemaError(
            f"No FARA rows matched featured countries {absent}. Check the "
            "spellings in data/reports/fara_country_review.json against "
            "config.FEATURED.")

    # Entities: one per registrant that appears in the records.
    entity_ids = {r["source_record_id"] for r in records}
    name_in_records = {}
    for r in records:
        name_in_records.setdefault(r["source_record_id"], r["entity_or_person_name"])
    entities = []
    for regnum in sorted(entity_ids, key=lambda x: (len(x), x)):
        reg = registrants.get(regnum, {})
        name = g(reg, R, "name") or name_in_records[regnum]
        entities.append({
            "entity_id": f"fara-{regnum}",
            "slug": f"{slugify(name)}-fara-{regnum}",
            "name": name,
            "source": "FARA",
            "registration_number": regnum,
            "registration_date": parse_mdy(g(reg, R, "reg_date")),
            "termination_date": parse_mdy(g(reg, R, "term_date")),
            "city": g(reg, R, "city"),
            "state": g(reg, R, "state"),
            "in_registrants_file": bool(reg),
        })

    # Every DOJ document for registrants with a featured-country principal,
    # so entity pages can link each supplemental statement directly.
    featured_regs = {r["source_record_id"] for r in records if r["featured"]}
    documents = {
        regnum: sorted(
            ({"date": d["date"], "type": d["type"], "url": d["url"],
              "foreign_principal": d["fp_name"]} for d in docs_by_reg.get(regnum, [])),
            key=lambda d: (d["date"] or "", d["url"]), reverse=True)
        for regnum in sorted(featured_regs)}

    report = {
        "rows_in_foreign_principals_file": len(fp_rows),
        "rows_in_registrants_file": len(reg_rows),
        "rows_in_document_index": len(doc_rows),
        "malformed_rows_skipped": {"registrants": reg_bad,
                                   "foreign_principals": fp_bad,
                                   "registrant_docs": doc_bad},
        "unparseable_dates": bad_dates,
        "records": len(records),
        "records_with_exhibit_link": sum(r["confidence"] == "verified" for r in records),
        "records_with_fallback_link": sum(r["confidence"] == "partial" for r in records),
        "featured_records_by_country": dict(Counter(
            r["country"] for r in records if r["featured"])),
        "columns_found": {"registrants": reg_h, "foreign_principals": fp_h,
                          "registrant_docs": doc_h},
    }
    write_json(config.REPORTS / "fara_clean_report.json", report)
    return {"records": records, "entities": entities,
            "documents": documents, "report": report}
