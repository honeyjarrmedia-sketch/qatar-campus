"""Turn the Department of Education Section 117 spreadsheet into records.

One record per row of the Department's file whose attribution country is a
featured country. Amounts, dates and names are copied as reported by the
institution. The file does not name the foreign source for most
transactions, so that field is usually empty here.

The free-text "Restricted Transaction Description" column is never read.
"""
import datetime as dt
from collections import Counter, defaultdict

from . import config
from .common import read_json, short_hash, slugify, title_country, write_json

REQUIRED = ["OPEID", "School Name", "State", "Transaction Type",
            "Foreign Government Source", "Attribution Country", "Amount",
            "Receipt Date", "Contract Start Date", "Contract End Date", "Legacy"]
OPTIONAL = ["Restricted Transaction Foreign Government Legal Name",
            "Restricted Transaction Foreign Government Name"]


class SchemaError(RuntimeError):
    pass


def _iso(value):
    if isinstance(value, (dt.datetime, dt.date)):
        return value.strftime("%Y-%m-%d")
    return None


def _text(value) -> str:
    return "" if value is None else " ".join(str(value).split())


def run() -> dict:
    import openpyxl

    entries = [e for e in (read_json(config.MANIFEST, {}) or {}).get("sec117", [])
               if e.get("status") == "ok"]
    if not entries:
        raise SchemaError("Section 117 spreadsheet not downloaded")
    entry = entries[-1]
    retrieved = entry["retrieved_at"][:10]
    through = entry["key"].replace("complete_through_", "")

    wb = openpyxl.load_workbook(config.ROOT / entry["path"], read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = None
    for _ in range(10):  # the header row follows a title block
        candidate = [_text(c) for c in next(rows)]
        if "OPEID" in candidate and "Attribution Country" in candidate:
            header = candidate
            break
    if header is None:
        raise SchemaError("Section 117 file: header row with OPEID not found in the first 10 rows")
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise SchemaError(f"Section 117 file is missing columns {missing}. Columns found: {header}")
    col = {name: header.index(name) for name in REQUIRED + [c for c in OPTIONAL if c in header]}

    featured = {v.upper(): cc for cc, meta in config.FEATURED.items()
                for v in meta["sec117_values"]}
    country_counts = Counter()
    countries_by_school = defaultdict(set)
    records, entities, seen = [], {}, Counter()
    total_rows = bad_amounts = 0
    for row in rows:
        if not row or all(c is None for c in row):
            continue
        total_rows += 1
        g = lambda name: row[col[name]] if name in col and col[name] < len(row) else None  # noqa: E731
        raw_country = _text(g("Attribution Country"))
        opeid = _text(g("OPEID"))
        country_counts[raw_country] += 1
        countries_by_school[opeid].add(raw_country.upper())
        cc = featured.get(raw_country.upper())
        try:
            amount = round(float(g("Amount")), 2)
        except (TypeError, ValueError):
            amount, bad_amounts = None, bad_amounts + 1
        receipt, start, end = _iso(g("Receipt Date")), _iso(g("Contract Start Date")), _iso(g("Contract End Date"))
        kind = _text(g("Transaction Type"))
        school = _text(g("School Name"))
        gov_flag = _text(g("Foreign Government Source"))
        named = _text(g("Restricted Transaction Foreign Government Legal Name")) or \
            _text(g("Restricted Transaction Foreign Government Name"))
        legacy = _text(g("Legacy")).lower() == "yes"

        details = [f"Foreign government source, as reported: {gov_flag or 'not stated'}"]
        if receipt:
            details.append(f"Receipt date: {receipt}")
        if start or end:
            details.append(f"Contract dates: {start or 'not stated'} to {end or 'not stated'}")
        notes = [f"The link opens the Department of Education spreadsheet of all public "
                 f"records reported through {through}; this row is found there by "
                 f"institution, date and amount."]
        if not named:
            notes.append("The Department's file does not name the foreign source for this transaction.")
        if legacy:
            notes.append("Reported through the Department's legacy system (before June 22, 2020).")
        if amount is not None and amount < 0:
            notes.append("A negative amount is an adjustment the institution reported to an earlier amount.")

        key = "|".join([opeid, kind, raw_country, str(amount), str(receipt), str(start), str(end)])
        seen[key] += 1
        rec_id = f"sec117-{short_hash(key + '|' + str(seen[key]))}"
        date = receipt or start
        records.append({
            "id": rec_id,
            "country": config.FEATURED[cc]["name"] if cc else title_country(raw_country),
            "country_code": cc or "",
            "country_as_filed": raw_country,
            "featured": bool(cc),
            "actor_type": "university",
            "entity_or_person_name": school,
            "entity_id": f"sec117-{opeid}",
            "role": "Institution that reported a foreign gift or contract under Section 117",
            "foreign_principal": named,
            "client_name": "",
            "amount_usd": amount,
            "amount_type": ("gift" if "gift" in kind.lower() else "contract") + " reported by the institution",
            "year": int(date[:4]) if date else None,
            "year_end": None,
            "date_start": date,
            "date_end": end,
            "period": "",
            "purpose": kind,
            "purpose_detail": ". ".join(details),
            "lobbyists": [],
            "source_url": entry["url"],
            "source_urls": [entry["url"]],
            "source_type": "Section 117 public records file (U.S. Department of Education)",
            "source_record_id": opeid,
            "link_basis": f"Attribution country is listed as {raw_country} in the Department of Education file",
            "confidence": "verified",
            "superseded": False,
            "date_retrieved": retrieved,
            "notes": " ".join(notes),
        })
        if f"sec117-{opeid}" not in entities:
            entities[f"sec117-{opeid}"] = {
                "entity_id": f"sec117-{opeid}",
                "slug": f"{slugify(school)}-sec117-{opeid}",
                "name": school, "source": "Section 117",
                "registration_number": opeid,
                "city": "", "state": _text(g("State")),
            }
    for eid, ent in entities.items():
        ent["countries_in_source"] = len(countries_by_school[ent["registration_number"]])

    found = {r["country_code"] for r in records}
    absent = [cc for cc in config.FEATURED if cc not in found]
    review = [{"country_as_filed": c, "rows": n, "mapped_to": featured.get(c.upper(), "")}
              for c, n in sorted(country_counts.items())
              if any(f in c.upper() for f in config.FARA_REVIEW_FRAGMENTS)]
    write_json(config.REPORTS / "sec117_country_review.json", review)
    if absent:
        raise SchemaError(f"No Section 117 rows matched featured countries {absent}. "
                          "Check data/reports/sec117_country_review.json against config.FEATURED.")
    report = {
        "rows_in_file": total_rows, "records": len(records),
        "countries": len({r["country"] for r in records}),
        "featured_records": sum(1 for r in records if r["featured"]),
        "records_by_country": dict(Counter(r["country"] for r in records)),
        "amount_total_by_country": {c: round(sum(r["amount_usd"] or 0 for r in records if r["country"] == c), 2)
                                    for c in sorted({r["country"] for r in records})},
        "rows_with_unreadable_amount": bad_amounts,
        "rows_with_no_date": sum(1 for r in records if r["year"] is None),
        "rows_with_named_source": sum(1 for r in records if r["foreign_principal"]),
        "negative_amount_rows": sum(1 for r in records if (r["amount_usd"] or 0) < 0),
        "institutions": len(entities), "records_through": through,
        "columns_found": header,
    }
    write_json(config.REPORTS / "sec117_clean_report.json", report)
    return {"records": records, "entities": list(entities.values()), "report": report}
