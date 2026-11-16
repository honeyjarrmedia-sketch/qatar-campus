"""Read the money out of FARA supplemental statements.

The Justice Department's bulk data carries no dollar amounts. They appear
only in Item 14(a) of each registrant's six-month supplemental statement,
as a table: one line per payment, with the foreign principal it relates to.

This reads that table from the PDF's text layer, using the position of the
column headings on the page to decide which words belong to which column.
Nothing is inferred:

  * A statement with no text layer (a scanned image) yields nothing.
  * A statement whose table says "See Appendix for Response" yields nothing;
    the appendix is free text and is not parsed.
  * The grand total is never taken. A statement covers every foreign
    principal the registrant acts for, so a total cannot be attributed to
    one country.
  * A line whose printed principal name does not match a principal in the
    Justice Department's own file for that registration is kept, but
    attributed to no country and flagged for review.

Every amount keeps the address of the PDF it came from and the page it was
printed on, so each figure can be checked against the filing.
"""
import re
from collections import Counter, defaultdict

from . import config
from .common import norm_name, read_json, read_records, short_hash, write_json

MONEY = re.compile(r"^\$?\s?([0-9][0-9,]*(?:\.[0-9]{2})?)$")
PERIOD = re.compile(r"Period\s+Ending\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", re.I)
SECTION = re.compile(r"14\.?\s*\(\s*a\s*\)", re.I)
END_SECTION = re.compile(r"\(\s*b\s*\)\s*RECEIPTS", re.I)
APPENDIX = re.compile(r"see\s+appendix", re.I)
# Words that mark a summary line rather than a payment line.
SUMMARY = re.compile(r"total|subtotal|arrancant", re.I)
DATE = re.compile(r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}\b")


def _lines(words, tol=3.0):
    """Group words into printed lines by their vertical position."""
    out = defaultdict(list)
    for w in words:
        key = round(w["top"] / tol)
        out[key].append(w)
    return [(k * tol, sorted(v, key=lambda w: w["x0"])) for k, v in sorted(out.items())]


def _columns(words):
    """Left edge of each column, taken from the table's own headings."""
    want = {"Principal": "principal", "Date": "date", "Whom": "whom",
            "Purpose": "purpose", "Amount": "amount", "Subtotal": "subtotal"}
    best = {}
    for w in words:
        key = want.get(w["text"].strip())
        if key and key not in best:
            best[key] = w
    if "amount" not in best or "principal" not in best:
        return None
    header_top = best["amount"]["top"]
    if any(abs(best[k]["top"] - header_top) > 6 for k in best):
        return None  # headings not on one line: not the table we want
    cols = {"principal_x1": best["date"]["x0"] - 4 if "date" in best else best["amount"]["x0"],
            "amount_x0": best["amount"]["x0"] - 6,
            "amount_x1": (best["subtotal"]["x0"] - 6) if "subtotal" in best else 10_000,
            "header_top": header_top}
    return cols if cols["principal_x1"] > 0 else None


def _page_rows(page, page_text: str) -> list:
    # "See Appendix for Response" can be split across printed lines, so the
    # whole page is judged, not one cell. Nothing is taken from such a page:
    # the figure shown on the form is then the registrant's grand total.
    if APPENDIX.search(page_text):
        return []
    words = page.extract_words()
    cols = _columns(words)
    if not cols:
        return []
    rows, pending_principal = [], ""
    for top, line in _lines(words):
        if top <= cols["header_top"] + 4:
            continue
        text_all = " ".join(w["text"] for w in line)
        if END_SECTION.search(text_all):
            break
        left = " ".join(w["text"] for w in line if w["x1"] <= cols["principal_x1"]).strip()
        if left and not SUMMARY.search(left):
            pending_principal = left if not APPENDIX.search(left) else ""
        # A payment line carries a date; the grand total and subtotals do not.
        if not any(DATE.search(w["text"]) and w["x1"] <= cols["amount_x0"] for w in line):
            continue
        money = [w for w in line
                 if cols["amount_x0"] <= w["x0"] < cols["amount_x1"]
                 and MONEY.match(w["text"].replace("$", "$ ").split("$")[-1].strip() or "x")]
        # The figure itself must sit in the Amount column, not in Subtotal.
        if not any(re.search(r"[0-9]", w["text"]) for w in money):
            continue
        if not money or SUMMARY.search(text_all):
            continue
        joined = "".join(w["text"] for w in money).replace("$", "").replace(" ", "")
        m = MONEY.match(joined)
        if not m or not pending_principal:
            continue
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if value <= 0:
            continue
        rows.append({"principal_as_printed": " ".join(pending_principal.split()),
                     "amount_usd": round(value, 2)})
    return rows


def extract_pdf(path, url: str) -> dict:
    """Return what one statement yields, with the reason when it yields nothing."""
    import pdfplumber

    result = {"url": url, "period_ending": None, "rows": [], "outcome": "",
              "pages_with_table": []}
    try:
        pdf = pdfplumber.open(path)
    except Exception as e:
        result["outcome"] = f"unreadable pdf: {str(e)[:120]}"
        return result
    with pdf:
        texts = []
        for page in pdf.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append("")
        whole = "\n".join(texts)
        if len(whole.strip()) < 200:
            result["outcome"] = "no text layer (scanned image)"
            return result
        m = PERIOD.search(whole)
        if m:
            d, mo, y = m.group(1).split("/")[1], m.group(1).split("/")[0], m.group(1).split("/")[2]
            result["period_ending"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        pages = [i for i, t in enumerate(texts) if SECTION.search(t) and re.search(r"RECEIPTS", t, re.I)]
        if not pages:
            result["outcome"] = "no Item 14(a) section found in the text"
            return result
        for i in pages[:3]:
            rows = _page_rows(pdf.pages[i], texts[i])
            if rows:
                result["pages_with_table"].append(i + 1)
                result["rows"].extend(rows)
        if result["rows"]:
            result["outcome"] = "extracted"
        elif any(APPENDIX.search(texts[i]) for i in pages):
            result["outcome"] = "table says: see appendix (not parsed)"
        else:
            result["outcome"] = "no payment lines found in the table"
    return result


def run(country_code: str = "QA") -> dict:
    """Read every downloaded statement for one country and build fee records."""
    manifest = (read_json(config.MANIFEST, {}) or {}).get(f"fara_docs_{country_code}", [])
    docs = [e for e in manifest if e.get("status") in ("ok", "cached") and e.get("path")]
    if not docs:
        raise RuntimeError(f"No downloaded statements for {country_code}")

    records = read_records(config.CLEAN / "records.json.gz")
    fara = [r for r in records if r["actor_type"] == "fara_registrant"]
    # Every principal the Justice Department lists under each registration,
    # with the country it is filed under.
    by_reg = defaultdict(dict)
    for r in fara:
        by_reg[r["source_record_id"]][norm_name(r["foreign_principal"])] = r
    reg_name = {r["source_record_id"]: r["entity_or_person_name"] for r in fara}

    outcomes, fee_records, unmatched = Counter(), [], []
    for doc in docs:
        path = config.ROOT / doc["path"]
        if not path.exists():
            outcomes["pdf not present in this checkout"] += 1
            continue
        res = extract_pdf(path, doc["url"])
        outcomes[res["outcome"]] += 1
        period = res["period_ending"] or doc.get("date")
        regnum = doc["regnum"]
        known = by_reg.get(regnum, {})
        for row in res["rows"]:
            printed = norm_name(row["principal_as_printed"])
            match = known.get(printed)
            if match is None:  # try a contained-name match, both directions
                hits = [v for k, v in known.items()
                        if k and printed and (k in printed or printed in k)]
                match = hits[0] if len(hits) == 1 else None
            if match is None:
                unmatched.append({"registration_number": regnum, "url": res["url"],
                                  "principal_as_printed": row["principal_as_printed"],
                                  "amount_usd": row["amount_usd"],
                                  "principals_on_file": sorted(
                                      v["foreign_principal"] for v in known.values())[:8]})
                continue
            rec_id = "farafee-" + short_hash(
                f"{regnum}|{printed}|{period}|{row['amount_usd']}|{res['url']}", 12)
            fee_records.append({
                "id": rec_id,
                "country": match["country"],
                "country_code": match["country_code"],
                "country_as_filed": match["country_as_filed"],
                "featured": match["featured"],
                "actor_type": "fara_fee",
                "entity_or_person_name": reg_name.get(regnum, match["entity_or_person_name"]),
                "entity_id": f"fara-{regnum}",
                "role": "Payment reported in the registrant's FARA supplemental statement",
                "foreign_principal": match["foreign_principal"],
                "client_name": "",
                "amount_usd": row["amount_usd"],
                "amount_type": "receipt reported in Item 14(a)",
                "year": int(period[:4]) if period else None,
                "year_end": None,
                "date_start": period,
                "date_end": None,
                "period": f"six months ending {period}" if period else "",
                "purpose": "",
                "purpose_detail": (
                    f"Printed on the statement as \"{row['principal_as_printed']}\" on page "
                    + ", ".join(str(p) for p in res["pages_with_table"]) + "."),
                "lobbyists": [],
                "source_url": res["url"],
                "source_urls": [res["url"]],
                "source_type": "FARA supplemental statement, Item 14(a)",
                "source_record_id": regnum,
                "link_basis": match["link_basis"],
                "confidence": "derived",
                "superseded": False,
                "date_retrieved": doc["retrieved_at"][:10],
                "notes": ("Read from the Item 14(a) receipts table of the linked "
                          "supplemental statement. The statement covers every foreign "
                          "principal of this registrant; only lines naming this "
                          "principal are counted here. Totals printed on the form are "
                          "never used."),
            })
    report = {
        "country_code": country_code,
        "statements_read": len(docs),
        "outcomes": dict(outcomes),
        "fee_records": len(fee_records),
        "amount_total": round(sum(r["amount_usd"] for r in fee_records), 2),
        "by_country": {c: round(sum(r["amount_usd"] for r in fee_records if r["country"] == c), 2)
                       for c in sorted({r["country"] for r in fee_records})},
        "lines_not_matched_to_a_principal": len(unmatched),
        "amount_not_matched": round(sum(u["amount_usd"] for u in unmatched), 2),
    }
    write_json(config.REPORTS / f"fara_fees_{country_code}.json", report)
    write_json(config.REPORTS / f"fara_fees_unmatched_{country_code}.json", unmatched[:400])
    write_json(config.CLEAN / f"fara_fees_{country_code}.json", fee_records)
    print(f"[fees] {country_code}: {len(fee_records)} fee lines, "
          f"${report['amount_total']:,.2f} | outcomes {dict(outcomes)}")
    return {"records": fee_records, "report": report}


if __name__ == "__main__":
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else "QA")
