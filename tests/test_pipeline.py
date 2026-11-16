"""Pipeline tests.

EVERYTHING IN THIS FILE IS SYNTHETIC. The names, numbers and links below are
invented to exercise the code and are written to a temporary directory that
is deleted afterwards. None of it is, or may ever be copied into, the
published dataset.
"""
import csv
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="qc-synthetic-")
os.environ["QC_ROOT"] = _TMP

from pipeline import build_dataset, clean_fara, clean_lda, config  # noqa: E402
from pipeline.common import parse_mdy, title_country, write_json  # noqa: E402
from pipeline.fetch_lda import filing_matches  # noqa: E402


def _zip_csv(path: Path, name: str, rows: list) -> None:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, buf.getvalue().encode("iso-8859-1"))


def _filing(uuid, rid, cid, year, period, ftype, posted, income,
            client_country="US", fe_country=None):
    return {
        "filing_uuid": uuid, "filing_type": ftype,
        "filing_type_display": "SYNTHETIC " + ftype,
        "filing_year": year, "filing_period": period,
        "filing_period_display": period, "dt_posted": posted,
        "filing_document_url": f"https://lda.gov/filings/public/filing/{uuid}/print/",
        "income": income, "expenses": None,
        "registrant": {"id": rid, "name": "SYNTHETIC TEST FIRM LLP",
                       "house_registrant_id": 1, "city": "Testville", "state": "DC"},
        "client": {"id": cid, "name": "SYNTHETIC CLIENT CO",
                   "country": client_country, "ppb_country": client_country,
                   "client_self_select": False, "client_government_entity": None},
        "lobbying_activities": [{
            "general_issue_code_display": "Trade (domestic/foreign)",
            "description": "Synthetic description.",
            "lobbyists": [{"lobbyist": {"first_name": "TEST", "last_name": "PERSON"}}]}],
        "foreign_entities": ([{"name": "SYNTHETIC FOREIGN ENTITY",
                               "country": fe_country, "ppb_country": fe_country}]
                             if fe_country else []),
        "affiliated_organizations": [],
    }


def setUpModule():
    raw = Path(_TMP) / "raw"
    _zip_csv(raw / "fara/reg.zip", "FARA_All_Registrants.csv", [
        ["Registration Number", "Registration Date", "Termination Date", "Name",
         "Business Name", "Address 1", "Address 2", "City", "State", "Zip"],
        ["9001", "01/15/2010", "", "Synthetic Test Firm LLP", "", "1 Test St", "", "Testville", "DC", "00000"],
        ["9002", "03/01/2015", "06/30/2018", "Synthetic Other Firm", "", "", "", "", "", ""],
    ])
    _zip_csv(raw / "fara/fp.zip", "FARA_All_ForeignPrincipals.csv", [
        ["Foreign Principal Termination Date", "Foreign Principal",
         "Foreign Principal Registration Date", "Country/Location Represented",
         "Registration Number", "Registration Date", "Registrant Name",
         "Address 1", "Address 2", "City", "State", "Zip"],
        ["", "Synthetic Ministry A", "02/01/2011", "QATAR", "9001", "01/15/2010", "Synthetic Test Firm LLP", "", "", "", "", ""],
        ["12/31/2016", "Synthetic Company B", "05/05/2014", "CHINA", "9001", "01/15/2010", "Synthetic Test Firm LLP", "", "", "", "", ""],
        ["", "Synthetic Board C", "not a date", "HONG KONG", "9002", "03/01/2015", "Synthetic Other Firm", "", "", "", "", ""],
        ["", "Synthetic Agency D", "01/01/2016", "RUSSIA", "9002", "03/01/2015", "Synthetic Other Firm", "", "", "", "", ""],
        ["", "Synthetic Agency E", "01/01/2016", "SAUDI ARABIA", "9002", "03/01/2015", "Synthetic Other Firm", "", "", "", "", ""],
        ["", "Synthetic Agency F", "01/01/2016", "TURKEY", "9002", "03/01/2015", "Synthetic Other Firm", "", "", "", "", ""],
        ["broken", "row", "with", "too", "few"],
    ])
    _zip_csv(raw / "fara/docs.zip", "FARA_All_RegistrantDocs.csv", [
        ["Date Stamped", "Registrant Name", "Registration Number", "Document Type",
         "Short Form Name", "Foreign Principal Name", "Foreign Principal Country", "URL"],
        ["02/01/2011", "Synthetic Test Firm LLP", "9001", "Exhibit AB", "", "SYNTHETIC  MINISTRY A.", "QATAR",
         "https://efile.fara.gov/docs/9001-Exhibit-AB-20110201-1.pdf"],
        ["07/30/2012", "Synthetic Test Firm LLP", "9001", "Supplemental Statement", "", "", "",
         "https://efile.fara.gov/docs/9001-Supplemental-Statement-20120730-1.pdf"],
    ])
    lda_dir = raw / "lda" / "CN"
    lda_dir.mkdir(parents=True)
    filings = [
        _filing("aaaa", 501, 601, 2020, "first_quarter", "Q1", "2020-04-20T10:00:00-04:00", "50000.00", "CN"),
        _filing("bbbb", 501, 601, 2020, "first_quarter", "Q1A", "2020-06-01T10:00:00-04:00", "60000.00", "CN"),
        _filing("cccc", 501, 601, 2020, "first_quarter", "RR", "2020-01-05T10:00:00-05:00", None, "CN"),
        _filing("dddd", 501, 602, 2021, "second_quarter", "Q2", "2021-07-20T10:00:00-04:00", None, "US", "RU"),
        _filing("eeee", 777, 603, 2021, "second_quarter", "Q2", "2021-07-20T10:00:00-04:00", "10000.00", "US"),
    ]
    with gzip.open(lda_dir / "client_country.jsonl.gz", "wt", encoding="utf-8") as f:
        for x in filings:
            f.write(json.dumps(x) + "\n")
    stamp = "2026-01-02T00:00:00Z"
    write_json(config.MANIFEST, {
        "fara": [
            {"key": "registrants", "status": "ok", "path": "raw/fara/reg.zip", "retrieved_at": stamp},
            {"key": "foreign_principals", "status": "ok", "path": "raw/fara/fp.zip", "retrieved_at": stamp},
            {"key": "registrant_docs", "status": "ok", "path": "raw/fara/docs.zip", "retrieved_at": stamp},
        ],
        "lda": [{"unfiltered_count": 2000000},
                {"status": "ok", "path": "raw/lda/CN/client_country.jsonl.gz", "retrieved_at": stamp}],
    })


def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


class Helpers(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_mdy("09/27/2024"), "2024-09-27")
        self.assertIsNone(parse_mdy("not a date"))
        self.assertIsNone(parse_mdy(""))

    def test_country_display(self):
        self.assertEqual(title_country("SAUDI ARABIA"), "Saudi Arabia")
        self.assertEqual(title_country("KOREA, REPUBLIC OF"), "Korea, Republic of")

    def test_filter_recheck(self):
        f = _filing("x", 1, 1, 2020, "p", "Q1", "", None, "CN", "QA")
        self.assertTrue(filing_matches(f, "client_country", "CN"))
        self.assertFalse(filing_matches(f, "client_country", "QA"))
        self.assertTrue(filing_matches(f, "foreign_entity_country", "QA"))
        self.assertFalse(filing_matches(f, "made_up_filter", "QA"))


class Fara(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = clean_fara.run()
        cls.by_fp = {r["foreign_principal"]: r for r in cls.res["records"]}

    def test_counts_and_malformed(self):
        self.assertEqual(len(self.res["records"]), 6)
        self.assertEqual(self.res["report"]["malformed_rows_skipped"]["foreign_principals"], 1)
        self.assertEqual(self.res["report"]["unparseable_dates"], 1)

    def test_exhibit_link_is_verified(self):
        r = self.by_fp["Synthetic Ministry A"]
        self.assertEqual(r["confidence"], "verified")
        self.assertTrue(r["source_url"].endswith("9001-Exhibit-AB-20110201-1.pdf"))
        self.assertEqual((r["country"], r["country_code"], r["year"]), ("Qatar", "QA", 2011))
        self.assertIsNone(r["amount_usd"])

    def test_no_exhibit_falls_back_and_is_flagged(self):
        r = self.by_fp["Synthetic Company B"]
        self.assertEqual(r["confidence"], "partial")
        self.assertEqual(r["source_url"], "https://efile.fara.gov/api/v1/RegDocs/html/9001")
        self.assertEqual(r["year_end"], 2016)

    def test_hong_kong_is_not_china(self):
        r = self.by_fp["Synthetic Board C"]
        self.assertFalse(r["featured"])
        self.assertEqual(r["country"], "Hong Kong")
        self.assertIsNone(r["year"])  # bad date is left empty, not guessed

    def test_wrong_columns_stop_the_build(self):
        with self.assertRaises(clean_fara.SchemaError):
            clean_fara.resolve(["Some", "Other", "Columns"], clean_fara.FP_COLS, {}, "test")


class Lda(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = clean_lda.run()
        cls.by_id = {r["id"]: r for r in cls.res["records"]}

    def test_amendment_supersedes_original(self):
        self.assertTrue(self.by_id["lda-aaaa-cn"]["superseded"])
        self.assertFalse(self.by_id["lda-bbbb-cn"]["superseded"])
        self.assertFalse(self.by_id["lda-cccc-cn"]["superseded"])  # registration
        self.assertEqual(self.by_id["lda-bbbb-cn"]["amount_usd"], 60000.0)

    def test_foreign_entity_link_states_its_basis(self):
        r = self.by_id["lda-dddd-ru"]
        self.assertIn("Foreign entity listed on the filing", r["link_basis"])
        self.assertEqual(r["foreign_principal"], "SYNTHETIC FOREIGN ENTITY")
        self.assertIsNone(r["amount_usd"])

    def test_unlinked_filing_is_dropped(self):
        self.assertFalse(any("eeee" in i for i in self.by_id))
        self.assertEqual(self.res["report"]["filings_with_no_featured_link_after_local_check"], 1)


class Build(unittest.TestCase):
    def test_full_build_validates_and_finds_overlap(self):
        self.assertEqual(build_dataset.run(), 0)
        clean = Path(_TMP) / "data" / "clean"
        records = json.loads((clean / "records.json").read_text())
        self.assertEqual(len(records), 10)
        conns = json.loads((clean / "connections.json").read_text())
        names = {c["entity_id"]: c["featured_countries"] for c in conns}
        self.assertEqual(names["fara-9001"], ["CN", "QA"])
        self.assertEqual(names["fara-9002"], ["RU", "SA", "TR"])
        self.assertEqual(names["lda-501"], ["CN", "RU"])
        with open(clean / "records.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 10)
        self.assertEqual(list(rows[0])[:14], build_dataset.CSV_COLUMNS[:14])

    def test_bad_source_link_fails_validation(self):
        bad = {"id": "x", "country": "Qatar", "actor_type": "a",
               "entity_or_person_name": "n", "role": "r",
               "source_url": "https://example.com/summary", "source_type": "s",
               "confidence": "verified", "date_retrieved": "2026-01-02"}
        self.assertTrue(build_dataset.validate([bad]))
        self.assertTrue(build_dataset.validate([dict(bad, source_url="")]))


if __name__ == "__main__":
    unittest.main()


class LdaFetchAgainstLocalFakeServer(unittest.TestCase):
    """Runs the downloader against a fake API on localhost (synthetic)."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading
        import urllib.parse as up

        def make(uuid, cc):
            return _filing(uuid, 1, 1, 2020, "first_quarter", "Q1", "2020-01-01", None, cc)

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                q = dict(up.parse_qsl(up.urlparse(self.path).query))
                base = f"http://127.0.0.1:{self.server.server_port}/filings/"
                if q.get("client_country") == "QA":
                    page = int(q.get("page", 1))
                    data = [make("q1", "QA"), make("q2", "QA"), make("q3", "QA")]
                    body = {"count": 3, "results": data[(page - 1) * 2: page * 2],
                            "next": base + "?client_country=QA&page=2" if page == 1 else None}
                elif "client_ppb_country" in q:  # wrong content for the filter
                    body = {"count": 1, "results": [make("zz", "US")], "next": None}
                elif "foreign_entity_country" in q:  # behaves like an ignored filter
                    body = {"count": 1000, "results": [make("yy", "US")], "next": None}
                elif "client_country" in q:
                    body = {"count": 0, "results": [], "next": None}
                else:
                    body = {"count": 1000, "results": [], "next": None}
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.saved = (config.LDA_API, config.LDA_FILTERS, config.LDA_SLEEP_ANON,
                     config.MANIFEST, dict(config.FEATURED))
        config.LDA_API = f"http://127.0.0.1:{cls.server.server_port}/filings/"
        config.LDA_FILTERS = ["client_country", "client_ppb_country", "foreign_entity_country"]
        config.LDA_SLEEP_ANON = 0
        config.MANIFEST = Path(_TMP) / "raw" / "MANIFEST-fetchtest.json"
        for cc in [c for c in config.FEATURED if c not in ("QA", "CN")]:
            config.FEATURED.pop(cc)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        (config.LDA_API, config.LDA_FILTERS, config.LDA_SLEEP_ANON,
         config.MANIFEST, featured) = cls.saved
        config.FEATURED.clear()
        config.FEATURED.update(featured)

    def test_pagination_and_guards(self):
        from pipeline import fetch_lda
        os.environ.pop("LDA_API_KEY", None)
        entries = {(e["country_code"], e["filter"]): e for e in fetch_lda.run()}
        ok = entries[("QA", "client_country")]
        self.assertEqual((ok["status"], ok["saved"], ok["api_count"]), ("ok", 3, 3))
        with gzip.open(Path(_TMP) / ok["path"], "rt") as f:
            self.assertEqual([json.loads(x)["filing_uuid"] for x in f], ["q1", "q2", "q3"])
        self.assertEqual(entries[("QA", "client_ppb_country")]["status"], "skipped")
        self.assertEqual(entries[("QA", "foreign_entity_country")]["status"], "skipped")
        self.assertEqual(entries[("CN", "client_country")]["saved"], 0)
