"""Build the one-page static site into site/ from data/clean/.

The page is plain HTML, CSS and JavaScript with no build tooling. The
default view (Qatar, all years) is written into the HTML itself so the page
has real content before any script runs; the script then takes over for
filtering. Every number written here is computed from data/clean/records.json.
"""
import html
import json
import shutil
import sys
from collections import Counter

from . import config
from .common import read_json, short_hash, write_json

WEB = config.ROOT / "web"
SITE = config.ROOT / "site"

FIELDS = ["id", "t", "country", "cc", "entity", "eid", "principal", "client",
          "amount", "amtType", "year", "yearEnd", "dStart", "dEnd", "period",
          "purpose", "detail", "people", "url", "urls", "srcType", "basis",
          "conf", "sup", "notes", "retrieved", "role"]
DICT_FIELDS = ["t", "country", "cc", "entity", "eid", "client", "amtType",
               "period", "purpose", "srcType", "basis", "conf", "notes",
               "retrieved", "role"]
STATIC_ROWS = 25
STATIC_CONN = 10


def compact_row(r: dict) -> dict:
    return {
        "id": r["id"],
        "t": "fara" if r["actor_type"] == "fara_registrant" else "lda",
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
    return {
        "count": sum(1 for r in scope if not r["sup"]),
        "registrants": len({r["eid"] for r in fara}),
        "principals": len({(r["principal"] or "").upper() for r in fara}),
        "filings": len(filings),
        "income": sum(r["amount"] for r in with_income),
        "income_n": len(with_income),
    }


def stat_html(label, value, foot) -> str:
    return (f'<div class="card stat"><div class="label">{esc(label)}</div>'
            f'<div class="stat-value">{esc(value)}</div>'
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
    kind = "FARA registration" if r["t"] == "fara" else "LDA filing"
    return (f'<tr><td>{esc(r["country"])}</td><td style="font-size: 14px">{kind}</td>'
            f'<td>{esc(r["entity"])}</td><td>{esc(r["principal"] or r["client"])}</td>'
            f'<td class="num">{amount}</td><td class="yr">{esc(year)}</td>'
            f'<td><a href="{esc(r["url"])}" rel="noopener" style="font-size: 14px; white-space: nowrap">Open filing</a></td>'
            f'<td><span class="tag tag-{esc(r["conf"])}">{esc(r["conf"])}</span></td></tr>')


def run() -> int:
    records = read_json(config.CLEAN / "records.json")
    if not records:
        print("[site] no records; run the clean step first", file=sys.stderr)
        return 1
    summary = read_json(config.CLEAN / "summary.json", {}) or {}
    conns = read_json(config.CLEAN / "connections.json", []) or []
    manifest = read_json(config.MANIFEST, {}) or {}
    cfg = read_json(config.ROOT / "site.config.json", {}) or {}

    rows = [compact_row(r) for r in records]
    retrieved = max(r["retrieved"] for r in rows)
    years = [r["year"] for r in rows if r["year"] is not None]
    year_min, year_max = min(years), max(max(years), int(retrieved[:4]))
    featured = [r for r in rows if r["cc"]]
    other = [r for r in rows if not r["cc"]]
    other_countries = sorted(Counter(r["country"] for r in other).items())

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "assets").mkdir(parents=True)
    (SITE / "data").mkdir()
    for name in ("app.js", "style.css"):
        shutil.copyfile(WEB / name, SITE / "assets" / name)
    shutil.copyfile(config.CLEAN / "records.csv", SITE / "data" / "records.csv")

    def dump(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

    dump(SITE / "data" / "featured.json", pack(featured, {
        "generated": summary.get("generated_at", ""), "year_min": year_min,
        "year_max": year_max, "other_countries": other_countries}))
    dump(SITE / "data" / "other.json", pack(other, {}))
    conn_small = [{"eid": c["entity_id"], "name": c["name"], "source": c["source"],
                   "cc": c["featured_countries"], "all": c["all_countries_in_dataset"],
                   "n": sum(len(v) for v in c["records_by_country"].values())}
                  for c in conns]
    dump(SITE / "data" / "connections.json", conn_small)

    # ---- Static (pre-script) content for the default Qatar view ----------
    q = qatar_totals(rows)
    stats = "".join([
        stat_html("FARA registrants", f'{q["registrants"]:,}', "Qatar, all years"),
        stat_html("Foreign principals", f'{q["principals"]:,}', "Qatar, all years"),
        stat_html("Lobbying filings", f'{q["filings"]:,}', "Qatar, all years"),
        stat_html("Lobbying income reported", money(q["income"]),
                  f'from {q["income_n"]:,} filings'),
    ])
    qatar = sorted((r for r in rows if r["cc"] == "QA" and not r["sup"]),
                   key=lambda r: (-(r["year"] or 0), r["id"]))
    static_rows = "".join(row_html(r, year_max) for r in qatar[:STATIC_ROWS])
    if not static_rows:
        static_rows = '<tr><td colspan="8" class="muted">No records.</td></tr>'
    names = {cc: m["name"] for cc, m in config.FEATURED.items()}
    conn_rows = "".join(
        f'<tr><td>{esc(c["name"])}<div class="sub">{esc(c["source"])} registrant</div></td>'
        f'<td>{esc(", ".join(names.get(x, x) for x in c["cc"]))}</td>'
        f'<td class="yr">{esc("featured countries only" if c["all"] is None else str(len(c["cc"])) + " of " + str(c["all"]))}</td>'
        f'<td>{c["n"]:,} records</td><td><span class="tag tag-derived">derived</span></td></tr>'
        for c in conn_small[:STATIC_CONN]) or (
        '<tr><td colspan="5" class="muted">No registrant has records in more than one featured country.</td></tr>')
    tabs = "".join(
        f'<button type="button" class="tab" data-c="{cc}" aria-pressed="{"true" if cc == "QA" else "false"}">{esc(name)}</button>'
        for cc, name in list(names.items()) + [("ALL", "All countries")])

    def fetched(source):
        dates = sorted({e["retrieved_at"][:10] for e in manifest.get(source, [])
                        if e.get("status") == "ok" and e.get("retrieved_at")})
        return dates[-1] if dates else None

    parts = []
    if fetched("fara"):
        parts.append(f"The FARA files were downloaded on {fetched('fara')}.")
    if fetched("lda"):
        parts.append(f"The lobbying filings were downloaded on {fetched('lda')}.")
    fara_rows = [r for r in rows if r["t"] == "fara"]
    partial = sum(1 for r in fara_rows if r["conf"] == "partial")
    partial_note = (f"{partial:,} of {len(fara_rows):,} FARA rows are marked partial for this reason."
                    if fara_rows else "")

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
        "name": f"{brand}: foreign agent registrations and lobbying filings in the United States",
        "description": description, "dateModified": retrieved,
        "isAccessibleForFree": True,
        "isBasedOn": ["https://efile.fara.gov/", "https://lda.gov/"],
        "creator": {"@type": "Organization", "name": brand},
    }
    if site_url:
        jsonld["url"] = site_url + "/"
        jsonld["distribution"] = [{"@type": "DataDownload", "encodingFormat": "text/csv",
                                   "contentUrl": site_url + "/data/records.csv"}]

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
        "PARTIAL_NOTE": esc(partial_note), "CONTACT": contact,
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

    sizes = {p.name: p.stat().st_size for p in (SITE / "data").iterdir()}
    write_json(config.REPORTS / "site_build.json", {
        "records": len(rows), "featured_records": len(featured),
        "other_records": len(other), "year_range": [year_min, year_max],
        "qatar_default_view": q, "data_file_bytes": sizes,
        "site_url_set": bool(site_url), "contact_email_set": bool(email)})
    print(f"[site] built {SITE} | records {len(rows)} | data files {sizes}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
