"""Build the one-page static site into site/ from data/clean/.

The page is plain HTML, CSS and JavaScript with no build tooling. The
default view (Qatar, all years) is written into the HTML itself so the page
has real content before any script runs; the script then takes over for
filtering. Every number written here is computed from data/clean/records.json.gz.
"""
import html
import json
import shutil
import sys
import zipfile
from collections import Counter, defaultdict

from . import config
from .common import read_json, read_records, short_hash, slugify, write_json

WEB = config.ROOT / "web"
SITE = config.ROOT / "site"

FIELDS = ["id", "t", "country", "cc", "entity", "eid", "principal", "client",
          "amount", "amtType", "year", "yearEnd", "dStart", "dEnd", "period",
          "purpose", "detail", "people", "url", "urls", "srcType", "basis",
          "conf", "sup", "notes", "retrieved", "role"]
DICT_FIELDS = ["t", "country", "cc", "entity", "eid", "client", "amtType",
               "period", "purpose", "srcType", "basis", "conf", "notes",
               "retrieved", "role"]
TYPES = {"fara_registrant": "fara", "lobbying_registrant": "lda", "university": "sec117",
         "fara_fee": "farafee"}
KIND = {"fara": "FARA registration", "lda": "LDA filing", "sec117": "University report",
        "farafee": "FARA payment"}
STATIC_ROWS = 25
STATIC_CONN = 10


def compact_row(r: dict) -> dict:
    return {
        "id": r["id"],
        "t": TYPES[r["actor_type"]],
        "country": r["country"], "cc": r["country_code"],
        "entity": r["entity_or_person_name"], "eid": r["entity_id"],
        "principal": r["foreign_principal"], "client": r.get("client_name", ""),
        "amount": r["amount_usd"], "amtType": r.get("amount_type", ""),
        "year": r["year"], "yearEnd": r.get("year_end"),
        "dStart": r.get("date_start"), "dEnd": r.get("date_end"),
        "period": r.get("period", ""), "purpose": r.get("purpose", ""),
        "detail": r.get("purpose_detail", ""),
        "people": "; ".join(r.get("lobbyists") or []),
        "url": r["source_url"],
        "urls": [u for u in (r.get("source_urls") or []) if u != r["source_url"]][:6],
        "srcType": r["source_type"], "basis": r.get("link_basis", ""),
        "conf": r["confidence"], "sup": 1 if r.get("superseded") else 0,
        "notes": r.get("notes", ""), "retrieved": r["date_retrieved"],
        "role": r["role"],
    }


def pack(rows: list, extra: dict) -> dict:
    tables = {f: {} for f in DICT_FIELDS}
    out = []
    for r in rows:
        line = []
        for f in FIELDS:
            v = r[f]
            if f in tables and v is not None:
                v = tables[f].setdefault(v, len(tables[f]))
            line.append(v)
        out.append(line)
    packed = {"fields": FIELDS,
              "dict": {f: list(t) for f, t in tables.items()},
              "rows": out}
    packed.update(extra)
    return packed


def money(n: float) -> str:
    return "${:,.0f}".format(n)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def qatar_totals(rows: list) -> dict:
    """Mirror of renderTotals() in web/app.js for the default view."""
    scope = [r for r in rows if r["cc"] == "QA"]
    fara = [r for r in scope if r["t"] == "fara"]
    filings = {}
    for r in scope:
        if r["t"] == "lda" and not r["sup"]:
            filings.setdefault(r["id"][4:r["id"].rfind("-")], r)
    with_income = [r for r in filings.values()
                   if r["amount"] is not None and r["amtType"].startswith("income")]
    uni = [r for r in scope if r["t"] == "sec117"]
    fees = [r for r in scope if r["t"] == "farafee"]
    return {
        "fees_total": sum(r["amount"] or 0 for r in fees),
        "fees_n": len(fees),
        "university_total": sum(r["amount"] or 0 for r in uni),
        "university_n": len(uni),
        "count": sum(1 for r in scope if not r["sup"]),
        "registrants": len({r["eid"] for r in fara}),
        "principals": len({(r["principal"] or "").upper() for r in fara}),
        "filings": len(filings),
        "income": sum(r["amount"] for r in with_income),
        "income_n": len(with_income),
    }


def big_money(n: float) -> str:
    """Mirror of bigMoney() in web/app.js."""
    if abs(n) >= 1e9:
        return "${:.2f} billion".format(n / 1e9)
    if abs(n) >= 1e6:
        return "${:.1f} million".format(n / 1e6)
    return money(n)


def stat_html(label, value, foot, exact=None) -> str:
    extra = (f'<div class="stat-exact">{esc(money(exact))} exactly</div>'
             if exact is not None and abs(exact) >= 1e6 else "")
    return (f'<div class="card stat"><div class="label">{esc(label)}</div>'
            f'<div class="stat-value">{esc(value)}</div>{extra}'
            f'<div class="stat-foot"><span>{esc(foot)}</span>'
            f'<span class="tag tag-derived">derived</span></div></div>')


def row_html(r: dict, year_max: int) -> str:
    if r["amount"] is not None:
        amount = esc(money(r["amount"]))
        if r["amtType"]:
            amount += f'<div class="sub">{esc(r["amtType"])}</div>'
    else:
        amount = "not in bulk data" if r["t"] == "fara" else "none stated"
    if r["year"] is None:
        year = "no date"
    elif r["t"] == "fara":
        year = f'{r["year"]}–{"present" if r["yearEnd"] is None else r["yearEnd"]}'
    else:
        year = str(r["year"])
    kind = KIND[r["t"]]
    return (f'<tr><td>{esc(r["country"])}</td><td style="font-size: 14px">{kind}</td>'
            f'<td>{esc(r["entity"])}</td><td>{esc(r["principal"] or r["client"]) or ("<span class=\"muted\" style=\"font-size: 14px\">not named in the file</span>" if r["t"] == "sec117" else "")}</td>'
            f'<td class="num">{amount}</td><td class="yr">{esc(year)}</td>'
            f'<td><a href="{esc(r["url"])}" rel="noopener" style="font-size: 14px; white-space: nowrap">Open filing</a></td>'
            f'<td><span class="tag tag-{esc(r["conf"])}">{esc(r["conf"])}</span></td></tr>')


def year_series_income(filings):
    out = defaultdict(float)
    for r in filings:
        if r["year"] is not None and r["amount"] is not None and (r["amtType"] or "").startswith("income"):
            out[r["year"]] += r["amount"]
    return {str(k): round(v, 2) for k, v in sorted(out.items())}


def run() -> int:
    records = read_records(config.CLEAN / "records.json.gz")
    if not records:
        print("[site] no records; run the clean step first", file=sys.stderr)
        return 1
    summary = read_json(config.CLEAN / "summary.json", {}) or {}
    conns = read_json(config.CLEAN / "connections.json", []) or []
    manifest = read_json(config.MANIFEST, {}) or {}
    cfg = read_json(config.ROOT / "site.config.json", {}) or {}

    rows = [compact_row(r) for r in records]
    retrieved = max(r["retrieved"] for r in rows)
    # The year range the page offers stops at the day the data was fetched.
    # A handful of filings carry a date typed years in the future (3030, 2999);
    # those are kept, shown with the date as filed, and treated as undated so
    # they can still be found instead of silently falling outside the range.
    year_max = int(retrieved[:4])
    years = [r["year"] for r in rows if r["year"] is not None and r["year"] <= year_max]
    year_min = min(years)
    impossible = []
    for r in rows:
        if r["year"] is not None and not (year_min <= r["year"] <= year_max):
            impossible.append({"id": r["id"], "country": r["country"], "entity": r["entity"],
                               "date_as_filed": r["dStart"], "year": r["year"],
                               "amount_usd": r["amount"], "source_url": r["url"]})
            r["notes"] = ((r["notes"] + " ") if r["notes"] else "") + (
                f"The date on this record is {r['dStart']}, which is outside the period "
                "the records cover. It is shown here as filed and left undated, so the "
                "year filter does not hide it.")
            r["year"] = None
            r["yearEnd"] = None
    write_json(config.REPORTS / "dates_outside_the_range.json", impossible)
    featured = [r for r in rows if r["cc"]]
    other = [r for r in rows if not r["cc"]]
    other_countries = sorted(Counter(r["country"] for r in other).items())

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "assets").mkdir(parents=True)
    (SITE / "data").mkdir()
    for name in ("app.js", "style.css"):
        shutil.copyfile(WEB / name, SITE / "assets" / name)
    # The full CSV is too large for a single file on Cloudflare Pages (25 MB
    # limit), so it is served zipped. The zip holds records.csv unchanged.
    import gzip as _gzip
    with zipfile.ZipFile(SITE / "data" / "records-csv.zip", "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        with _gzip.open(config.CLEAN / "records.csv.gz", "rb") as f:
            z.writestr("records.csv", f.read())

    def dump(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

    # Every country is its own file, fetched when that country is chosen, so
    # the page opens with Qatar alone however large the dataset grows.
    by_country = defaultdict(list)
    for r in rows:
        by_country[r["country"]].append(r)
    slugs, used = {}, set()
    for name in sorted(by_country):
        slug = slugify(name) or "country"
        while slug in used:
            slug += "-x"
        used.add(slug)
        slugs[name] = slug
    featured_names = {m["name"]: cc for cc, m in config.FEATURED.items()}
    index = [{"name": n, "slug": slugs[n], "n": len(by_country[n]),
              "cc": featured_names.get(n, "")}
             for n in sorted(by_country)]

    (SITE / "data" / "country").mkdir()
    for name, rows_for in by_country.items():
        dump(SITE / "data" / "country" / f"{slugs[name]}.json", pack(rows_for, {}))
    dump(SITE / "data" / "index.json", {
        "generated": summary.get("generated_at", ""), "year_min": year_min,
        "year_max": year_max, "countries": index,
        "featured": [[cc, m["name"], slugs.get(m["name"], "")]
                     for cc, m in config.FEATURED.items()]})

    # Which country files hold a given organisation's records, so "show all
    # records for this registrant" can fetch just those.
    ent_countries = defaultdict(set)
    for r in rows:
        ent_countries[r["eid"]].add(slugs[r["country"]])
    dump(SITE / "data" / "entity_countries.json",
         {k: sorted(v) for k, v in sorted(ent_countries.items()) if len(v) > 1})

    conn_small = [{"eid": c["entity_id"], "name": c["name"], "source": c["source"],
                   "cc": c["featured_countries"], "all": c["all_countries_in_dataset"],
                   "n": sum(len(v) for v in c["records_by_country"].values())}
                  for c in conns]
    dump(SITE / "data" / "connections.json", conn_small)

    # Totals and the year series for the "All countries" view, so it needs no
    # record-level download. Computed the same way as the page computes them.
    def year_series(rows_in, kind):
        out = defaultdict(float)
        for r in rows_in:
            if r["t"] != kind or r["year"] is None:
                continue
            if kind == "fara":
                end = year_max if r["yearEnd"] is None else r["yearEnd"]
                for y in range(max(r["year"], year_min), min(end, year_max) + 1):
                    out[y] += 1
            elif kind == "lda":
                if not r["sup"]:
                    out[r["year"]] += 1
            elif r["amount"] is not None:
                out[r["year"]] += r["amount"]
        return {str(k): round(v, 2) for k, v in sorted(out.items())}

    all_fara = [r for r in rows if r["t"] == "fara"]
    all_uni = [r for r in rows if r["t"] == "sec117"]
    all_fee = [r for r in rows if r["t"] == "farafee"]
    all_filings = {}
    for r in rows:
        if r["t"] == "lda" and not r["sup"]:
            all_filings.setdefault(r["id"][4:r["id"].rfind("-")], r)
    income = [r for r in all_filings.values()
              if r["amount"] is not None and r["amtType"].startswith("income")]
    dump(SITE / "data" / "summary.json", {
        "records": len(rows),
        "tiles": {
            "registrants": len({r["eid"] for r in all_fara}),
            "principals": len({(r["principal"] or "").upper() for r in all_fara}),
            "filings": len(all_filings),
            "income": round(sum(r["amount"] for r in income), 2),
            "income_n": len(income),
            "university_total": round(sum(r["amount"] or 0 for r in all_uni), 2),
            "university_n": len(all_uni),
            "fees_total": round(sum(r["amount"] or 0 for r in all_fee), 2),
            "fees_n": len(all_fee),
        },
        "series": {"fara": year_series(rows, "fara"), "lda": year_series(rows, "lda"),
                   "income": year_series_income(all_filings.values()),
                   "uni": year_series(rows, "sec117"), "fee": year_series(rows, "farafee")},
    })

    # ---- Static (pre-script) content for the default Qatar view ----------
    q = qatar_totals(rows)
    stats = "".join([
        stat_html("University gifts and contracts reported", big_money(q["university_total"]),
                  f'from {q["university_n"]:,} reports', q["university_total"]),
        stat_html("FARA registrants", f'{q["registrants"]:,}', "Qatar, all years"),
        stat_html("Foreign principals", f'{q["principals"]:,}', "Qatar, all years"),
        stat_html("Lobbying filings", f'{q["filings"]:,}', "Qatar, all years"),
        stat_html("Lobbying income reported", big_money(q["income"]),
                  f'from {q["income_n"]:,} filings', q["income"]),
    ] + ([stat_html("FARA payments read from statements", big_money(q["fees_total"]),
                    f'from {q["fees_n"]:,} reported payments', q["fees_total"])]
         if q["fees_n"] else []))
    qatar = sorted((r for r in rows if r["cc"] == "QA" and not r["sup"]),
                   key=lambda r: (-(r["year"] or 0), r["id"]))
    static_rows = "".join(row_html(r, year_max) for r in qatar[:STATIC_ROWS])
    if not static_rows:
        static_rows = '<tr><td colspan="8" class="muted">No records.</td></tr>'
    names = {cc: m["name"] for cc, m in config.FEATURED.items()}
    conn_rows = "".join(
        f'<tr><td>{esc(c["name"])}<div class="sub">{esc("Institution reporting under Section 117" if c["source"] == "Section 117" else c["source"] + " registrant")}</div></td>'
        f'<td>{esc(", ".join(names.get(x, x) for x in c["cc"]))}</td>'
        f'<td class="yr">{esc("not known for lobbying filings" if c["all"] is None else str(len(c["cc"])) + " of " + str(c["all"]))}</td>'
        f'<td>{c["n"]:,} records</td><td><span class="tag tag-derived">derived</span></td></tr>'
        for c in conn_small[:STATIC_CONN]) or (
        '<tr><td colspan="5" class="muted">No registrant has records in more than one featured country.</td></tr>')
    tabs = "".join(
        f'<button type="button" class="tab" data-c="{esc(slug)}" '
        f'aria-pressed="{"true" if slug == "qatar" else "false"}">{esc(name)}</button>'
        for slug, name in [(slugs.get(m["name"], ""), m["name"]) for m in config.FEATURED.values()]
        + [("ALL", "All countries")])

    def fetched(source):
        dates = sorted({e["retrieved_at"][:10] for e in manifest.get(source, [])
                        if e.get("status") == "ok" and e.get("retrieved_at")})
        return dates[-1] if dates else None

    parts = []
    if fetched("fara"):
        parts.append(f"The FARA files were downloaded on {fetched('fara')}.")
    if fetched("lda"):
        parts.append(f"The lobbying filings were downloaded on {fetched('lda')}.")
    if fetched("sec117"):
        parts.append(f"The Department of Education file was downloaded on {fetched('sec117')}.")
    fara_rows = [r for r in rows if r["t"] == "fara"]
    partial = sum(1 for r in fara_rows if r["conf"] == "partial")
    partial_note = (f"{partial:,} of {len(fara_rows):,} FARA rows are marked partial for this reason."
                    if fara_rows else "")

    fee_reports = sorted(config.REPORTS.glob("fara_fees_[A-Z][A-Z].json"))
    fee_bits = []
    for fp in fee_reports:
        fr = read_json(fp, {}) or {}
        read_n = fr.get("statements_read", 0)
        got = fr.get("outcomes", {}).get("extracted", 0)
        if read_n:
            fee_bits.append(f"Of {read_n:,} statements read so far, {got:,} had a "
                            f"readable receipts table.")
    fee_note = " ".join(fee_bits) or ("No statements have been read yet, so no FARA "
                                      "payment figures appear on this page.")

    email = (cfg.get("contact_email") or "").strip()
    contact = (f'<a href="mailto:{esc(email)}">{esc(email)}</a>' if email
               else '<span class="mono">[contact address not set]</span>')
    log = [c for c in cfg.get("changelog", []) if c.get("date") and c.get("text")]
    changelog = ('<ul class="changelog">' + "".join(
        f'<li><span class="mono">{esc(c["date"])}</span><span>{esc(c["text"])}</span></li>'
        for c in log) + "</ul>") if log else "<p>No changes have been logged yet.</p>"
    commentary = cfg.get("commentary_html") or (
        "<p>No commentary has been published. Opinion and argument, when added, "
        "appear only in this section and never in the totals, tables or methodology above.</p>")

    site_url = (cfg.get("site_url") or "").rstrip("/")
    brand = cfg.get("brand_name", "Qatar Campus")
    description = cfg.get("meta_description", "")
    jsonld = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"{brand}: foreign principals in United States disclosure records",
        "description": description, "dateModified": retrieved,
        "isAccessibleForFree": True,
        "isBasedOn": ["https://efile.fara.gov/", "https://lda.gov/", "https://fsapartners.ed.gov/"],
        "creator": {"@type": "Organization", "name": brand},
    }
    if site_url:
        jsonld["url"] = site_url + "/"
        jsonld["distribution"] = [{"@type": "DataDownload", "encodingFormat": "text/csv",
                                   "contentUrl": site_url + "/data/records-csv.zip"}]

    version = short_hash(json.dumps([summary.get("generated_at"), len(rows)]) +
                         (WEB / "app.js").read_text() + (WEB / "style.css").read_text(), 8)
    page = (WEB / "index.template.html").read_text(encoding="utf-8")
    for key, value in {
        "BRAND": esc(brand), "TAGLINE": esc(cfg.get("brand_tagline", "")),
        "META_DESCRIPTION": esc(description),
        "CANONICAL": f'<link rel="canonical" href="{esc(site_url)}/">' if site_url else "",
        "VERSION": version,
        "JSONLD": json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/"),
        "LAST_UPDATED": esc(retrieved), "TABS": tabs,
        "YEAR_MIN": str(year_min), "YEAR_MAX": str(year_max),
        "STATS": stats, "QATAR_COUNT": f'{q["count"]:,}',
        "STATIC_ROWS": static_rows,
        "STATIC_PAGE_INFO": f'Showing 1–{min(STATIC_ROWS, len(qatar))} of {len(qatar):,}' if qatar else "Showing 0 records",
        "CONN_ROWS": conn_rows, "SOURCE_DATES": esc(" ".join(parts)),
        "PARTIAL_NOTE": esc(partial_note), "FEE_NOTE": esc(fee_note), "CONTACT": contact,
        "CHANGELOG": changelog, "COMMENTARY": commentary,
        "CREDIT": esc(cfg.get("footer_credit", "")),
    }.items():
        page = page.replace(f"@@{key}@@", value)
    if "@@" in page:
        print("[site] unreplaced placeholder in template", file=sys.stderr)
        return 1
    (SITE / "index.html").write_text(page, encoding="utf-8")

    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n" + (f"Sitemap: {site_url}/sitemap.xml\n" if site_url else ""),
        encoding="utf-8")
    if site_url:
        (SITE / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{esc(site_url)}/</loc><lastmod>{esc(retrieved)}</lastmod></url>\n"
            "</urlset>\n", encoding="utf-8")
    (SITE / "_headers").write_text(
        "/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n"
        "/data/*\n  Cache-Control: public, max-age=3600\n", encoding="utf-8")

    sizes = {p.name: p.stat().st_size for p in (SITE / "data").iterdir() if p.is_file()}
    country_sizes = sorted(((p.stat().st_size, p.name)
                            for p in (SITE / "data" / "country").iterdir()), reverse=True)
    sizes["country/ (largest)"] = f"{country_sizes[0][1]} {country_sizes[0][0]:,}" if country_sizes else "none"
    sizes["country/ (files)"] = len(country_sizes)
    too_big = {n: b for n, b in sizes.items() if isinstance(b, int) and b > 24 * 1024 * 1024}
    if too_big:
        print(f"[site] files over the 25 MB hosting limit: {too_big}", file=sys.stderr)
        return 1
    write_json(config.REPORTS / "site_build.json", {
        "records": len(rows), "featured_records": len(featured),
        "other_records": len(other), "countries": len(index),
        "year_range": [year_min, year_max],
        "qatar_default_view": q, "data_file_bytes": sizes,
        "site_url_set": bool(site_url), "contact_email_set": bool(email)})
    print(f"[site] built {SITE} | records {len(rows)} | data files {sizes}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
