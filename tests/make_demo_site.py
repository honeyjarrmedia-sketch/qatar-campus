"""Build a throwaway copy of the site from SYNTHETIC data, for layout testing.

Every name and number produced here is invented. The script refuses to run
unless QC_ROOT points at a directory outside the repository, so nothing it
writes can reach raw/, data/ or site/.

    QC_ROOT=/tmp/qc-demo python tests/make_demo_site.py
"""
import csv
import gzip
import io
import json
import os
import random
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
root = os.environ.get("QC_ROOT")
if not root or Path(root).resolve() == REPO or REPO in Path(root).resolve().parents:
    sys.exit("Set QC_ROOT to a directory outside the repository.")
ROOT = Path(root)
if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True)
shutil.copytree(REPO / "web", ROOT / "web")
shutil.copyfile(REPO / "site.config.json", ROOT / "site.config.json")
sys.path.insert(0, str(REPO))

from pipeline import build_dataset, build_site, config  # noqa: E402
from pipeline.common import write_json  # noqa: E402

rnd = random.Random(7)
COUNTRIES = ["QATAR"] * 6 + ["CHINA"] * 8 + ["RUSSIA"] * 5 + ["SAUDI ARABIA"] * 6 + ["TURKEY"] * 5 + \
            ["JAPAN", "HONG KONG", "TAIWAN", "CANADA", "KOREA, REPUBLIC OF", "GERMANY"] * 3


def zip_csv(path, name, rows):
    buf = io.StringIO(); csv.writer(buf).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, buf.getvalue().encode("iso-8859-1"))


regs = [["Registration Number", "Registration Date", "Termination Date", "Name", "Business Name",
         "Address 1", "Address 2", "City", "State", "Zip"]]
fps = [["Foreign Principal Termination Date", "Foreign Principal", "Foreign Principal Registration Date",
        "Country/Location Represented", "Registration Number", "Registration Date", "Registrant Name",
        "Address 1", "Address 2", "City", "State", "Zip"]]
docs = [["Date Stamped", "Registrant Name", "Registration Number", "Document Type", "Short Form Name",
         "Foreign Principal Name", "Foreign Principal Country", "URL"]]
for i in range(90):
    num = str(9000 + i); name = f"Synthetic Firm {i:03d} LLP"
    regs.append([num, "01/15/1995", "", name, "", "", "", "Testville", "DC", ""])
    for j in range(rnd.randint(1, 7)):
        country = rnd.choice(COUNTRIES); start = rnd.randint(1996, 2025)
        end = "" if rnd.random() < 0.4 else f"12/31/{min(2026, start + rnd.randint(0, 9))}"
        fp = f"Synthetic Principal {i:03d}-{j}"
        fps.append([end, fp, f"03/01/{start}", country, num, "01/15/1995", name, "", "", "", "", ""])
        if rnd.random() < 0.7:
            docs.append([f"03/01/{start}", name, num, "Exhibit AB", "", fp, country,
                         f"https://efile.fara.gov/docs/{num}-Exhibit-AB-{start}0301-{j}.pdf"])
raw = ROOT / "raw"
zip_csv(raw / "fara/reg.zip", "r.csv", regs)
zip_csv(raw / "fara/fp.zip", "f.csv", fps)
zip_csv(raw / "fara/docs.zip", "d.csv", docs)

filings = []
for k in range(700):
    cc = rnd.choice(["QA", "CN", "CN", "CN", "RU", "SA", "SA", "TR"])
    year = rnd.randint(2000, 2026); q = rnd.choice(["first_quarter", "second_quarter", "third_quarter", "fourth_quarter"])
    rid = 500 + rnd.randint(0, 40); self_filer = rnd.random() < 0.15
    income = None if rnd.random() < 0.15 else f"{rnd.choice([10, 20, 30, 50, 80, 120, 250]) * 1000}.00"
    filings.append({
        "filing_uuid": f"{k:08d}-0000-4000-8000-000000000000", "filing_type": "Q1",
        "filing_type_display": "Quarterly report", "filing_year": year, "filing_period": q,
        "filing_period_display": q.replace("_", " "), "dt_posted": f"{year}-04-20T10:00:{k % 60:02d}-04:00",
        "filing_document_url": f"https://lda.gov/filings/public/filing/{k:08d}-0000-4000-8000-000000000000/print/",
        "income": None if self_filer else income, "expenses": income if self_filer else None,
        "registrant": {"id": rid, "name": f"SYNTHETIC LOBBY SHOP {rid}", "house_registrant_id": 1, "city": "", "state": ""},
        "client": {"id": 600 + k % 120, "name": f"SYNTHETIC CLIENT {k % 120}", "country": cc, "ppb_country": cc,
                   "client_self_select": self_filer, "client_government_entity": None},
        "lobbying_activities": [{"general_issue_code_display": rnd.choice(["Trade (domestic/foreign)", "Energy/Nuclear", "Defense"]),
                                 "description": "Synthetic description of issues.",
                                 "lobbyists": [{"lobbyist": {"first_name": "TEST", "last_name": f"PERSON{k % 9}"}}]}],
        "foreign_entities": [], "affiliated_organizations": []})
(raw / "lda" / "ALL").mkdir(parents=True)
with gzip.open(raw / "lda/ALL/client_country.jsonl.gz", "wt", encoding="utf-8") as f:
    for x in filings:
        f.write(json.dumps(x) + "\n")
import datetime as dt  # noqa: E402
SEC117_HEADER = ["OPEID", "School Name", "State", "Transaction Type", "Foreign Government Source",
                 "Attribution Country", "Amount", "Receipt Date", "Contract Start Date", "Contract End Date",
                 "Restricted Transaction Foreign Government Legal Name",
                 "Restricted Transaction Foreign Government Name", "Restricted Transaction Description",
                 "Institution Owned by Foreign Source", "Foreign Source Owner Name",
                 "Foreign Source Ownership Date", "Changes Due to Foreign Source Owner", "Legacy"]
import openpyxl  # noqa: E402
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["SYNTHETIC title block"]); ws.append(SEC117_HEADER)
for k in range(400):
    c = rnd.choice(["QATAR"] * 4 + ["CHINA"] * 4 + ["SAUDI ARABIA"] * 3 + ["RUSSIA", "TURKEY (TURKIYE)", "FRANCE"])
    y = rnd.randint(2008, 2024); school = rnd.randint(0, 14)
    ws.append([f"009{school:05d}", f"Synthetic University {school}", "TX", rnd.choice(["Contract", "Gift"]), rnd.choice(["Yes", "No", "N/A"]),
               c, rnd.choice([250, 300, 500, 900, 2500]) * 1000, dt.datetime(y, 6, 1), None, None, None, None, None, None, None, None, None, "No"])
(raw / "sec117").mkdir(parents=True)
wb.save(raw / "sec117" / "synthetic.xlsx")
stamp = "2026-11-16T00:00:00Z"
write_json(config.MANIFEST, {
    "sec117": [{"key": "complete_through_2025-02-28", "status": "ok", "path": "raw/sec117/synthetic.xlsx",
                "url": "https://fsapartners.ed.gov/sites/default/files/synthetic.xlsx", "retrieved_at": stamp}],
    "fara": [{"key": k, "status": "ok", "path": f"raw/fara/{p}.zip", "retrieved_at": stamp}
             for k, p in (("registrants", "reg"), ("foreign_principals", "fp"), ("registrant_docs", "docs"))],
    "lda": [{"status": "ok", "path": "raw/lda/ALL/client_country.jsonl.gz", "retrieved_at": stamp}]})
assert build_dataset.run() == 0
assert build_site.run() == 0
print("demo site at", ROOT / "site")
