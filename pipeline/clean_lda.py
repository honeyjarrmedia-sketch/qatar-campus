"""Turn raw LDA filings into records.

One record per filing per featured country the filing is linked to. The
link is always something written on the filing itself (the client's country,
or a foreign entity / affiliated organisation listed on it), and the record
says which.

A country here is where a client or listed entity is located. It does not
mean the filing involves that country's government.
"""
import gzip
import json
from collections import Counter, defaultdict

from . import config
from .common import read_json, slugify, write_json


def _load_filings() -> tuple:
    entries = [e for e in (read_json(config.MANIFEST, {}) or {}).get("lda", [])
               if e.get("status") == "ok" and e.get("path")]
    filings, retrieved = {}, {}
    for e in entries:
        with gzip.open(config.ROOT / e["path"], "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                filing = json.loads(line)
                uuid = filing.get("filing_uuid")
                if uuid and uuid not in filings:
                    filings[uuid] = filing
                    retrieved[uuid] = e["retrieved_at"][:10]
    return filings, retrieved


def country_links(filing: dict, cc: str) -> list:
    """Every reason, stated on the filing, that ties it to country cc."""
    name = config.FEATURED[cc]["name"]
    client = filing.get("client") or {}
    reasons = []
    if client.get("country") == cc:
        reasons.append(f"Client's country is listed as {name}")
    if client.get("ppb_country") == cc:
        reasons.append(f"Client's principal place of business is listed as {name}")
    for label, key in (("Foreign entity", "foreign_entities"),
                       ("Affiliated organization", "affiliated_organizations")):
        for e in filing.get(key) or []:
            if e.get("country") == cc or e.get("ppb_country") == cc:
                reasons.append(f"{label} listed on the filing: {e.get('name')} ({name})")
    # De-duplicate while keeping order.
    return list(dict.fromkeys(reasons))


def _amount(filing: dict):
    for field, label in (("income", "income reported by the registrant"),
                         ("expenses", "expenses reported by the registrant")):
        v = filing.get(field)
        if v not in (None, ""):
            try:
                return round(float(v), 2), label
            except (TypeError, ValueError):
                return None, f"{field} not numeric on filing"
    return None, ""


def _purpose(filing: dict) -> tuple:
    acts = filing.get("lobbying_activities") or []
    issues = list(dict.fromkeys(
        a.get("general_issue_code_display") for a in acts
        if a.get("general_issue_code_display")))
    descs = [a.get("description").strip() for a in acts if a.get("description")]
    detail = " | ".join(dict.fromkeys(descs))
    if len(detail) > 400:
        detail = detail[:397].rstrip() + "..."
    return "; ".join(issues), detail


def _lobbyists(filing: dict) -> list:
    names = []
    for a in filing.get("lobbying_activities") or []:
        for item in a.get("lobbyists") or []:
            p = item.get("lobbyist") or {}
            full = " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
            if full:
                names.append(full)
    return sorted(set(names))


def run() -> dict:
    filings, retrieved = _load_filings()

    # Amendments: within the same registrant, client, year and period, the
    # most recently posted report replaces earlier ones. Registrations
    # (types starting with "R") carry no amounts and are left alone.
    groups = defaultdict(list)
    for uuid, f in filings.items():
        if str(f.get("filing_type", "")).startswith("R"):
            continue
        key = ((f.get("registrant") or {}).get("id"),
               (f.get("client") or {}).get("id"),
               f.get("filing_year"), f.get("filing_period"))
        groups[key].append((f.get("dt_posted") or "", uuid))
    superseded = set()
    for items in groups.values():
        items.sort()
        superseded.update(uuid for _, uuid in items[:-1])

    records, entities = [], {}
    unlinked = 0
    for uuid, f in sorted(filings.items(), key=lambda kv: (kv[1].get("dt_posted") or "", kv[0])):
        registrant = f.get("registrant") or {}
        client = f.get("client") or {}
        amount, amount_type = _amount(f)
        purpose, purpose_detail = _purpose(f)
        self_filer = client.get("client_self_select") is True
        linked = False
        for cc in config.FEATURED:
            reasons = country_links(f, cc)
            if not reasons:
                continue
            linked = True
            foreign_names = [e.get("name") for key in ("foreign_entities", "affiliated_organizations")
                             for e in (f.get(key) or [])
                             if e.get("country") == cc or e.get("ppb_country") == cc]
            client_based = client.get("country") == cc or client.get("ppb_country") == cc
            notes = []
            if client.get("client_government_entity") is True:
                notes.append("Client is marked as a government entity on the filing.")
            if uuid in superseded:
                notes.append("A later report for the same registrant, client and "
                             "period exists; this one is excluded from totals.")
            if amount is None and not str(f.get("filing_type", "")).startswith("R"):
                notes.append("No amount stated on this filing.")
            records.append({
                "id": f"lda-{uuid}-{cc.lower()}",
                "country": config.FEATURED[cc]["name"],
                "country_code": cc,
                "country_as_filed": cc,
                "featured": True,
                "actor_type": "lobbying_registrant",
                "entity_or_person_name": registrant.get("name") or "",
                "entity_id": f"lda-{registrant.get('id')}",
                "role": ("Organization filing its own lobbying report"
                         if self_filer else "Lobbying registrant reporting for a client"),
                "foreign_principal": (client.get("name") if client_based
                                      else "; ".join(n for n in foreign_names if n)) or "",
                "client_name": client.get("name") or "",
                "amount_usd": amount,
                "amount_type": amount_type,
                "year": f.get("filing_year"),
                "year_end": None,
                "date_start": (f.get("dt_posted") or "")[:10] or None,
                "date_end": None,
                "period": f.get("filing_period_display") or f.get("filing_period") or "",
                "purpose": purpose,
                "purpose_detail": purpose_detail,
                "lobbyists": _lobbyists(f),
                "source_url": f.get("filing_document_url") or "",
                "source_urls": [f.get("filing_document_url")] if f.get("filing_document_url") else [],
                "source_type": f"LDA filing ({f.get('filing_type_display') or f.get('filing_type')})",
                "source_record_id": uuid,
                "link_basis": "; ".join(reasons),
                "confidence": "verified",
                "superseded": uuid in superseded,
                "date_retrieved": retrieved[uuid],
                "notes": " ".join(notes),
            })
        if not linked:
            unlinked += 1
            continue
        rid = registrant.get("id")
        if rid is not None and f"lda-{rid}" not in entities:
            name = registrant.get("name") or ""
            entities[f"lda-{rid}"] = {
                "entity_id": f"lda-{rid}",
                "slug": f"{slugify(name)}-lda-{rid}",
                "name": name,
                "source": "LDA",
                "registration_number": str(rid),
                "house_registrant_id": registrant.get("house_registrant_id"),
                "city": registrant.get("city") or "",
                "state": registrant.get("state") or "",
            }

    report = {
        "distinct_filings_downloaded": len(filings),
        "filings_with_no_featured_link_after_local_check": unlinked,
        "records": len(records),
        "records_superseded_by_later_report": sum(r["superseded"] for r in records),
        "records_with_amount": sum(r["amount_usd"] is not None for r in records),
        "records_by_country": dict(Counter(r["country"] for r in records)),
        "filing_types": dict(Counter(f.get("filing_type") for f in filings.values())),
        "year_range": [min((f.get("filing_year") for f in filings.values()
                            if f.get("filing_year")), default=None),
                       max((f.get("filing_year") for f in filings.values()
                            if f.get("filing_year")), default=None)],
    }
    write_json(config.REPORTS / "lda_clean_report.json", report)
    return {"records": records, "entities": list(entities.values()), "report": report}
