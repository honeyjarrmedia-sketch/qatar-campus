"""Central configuration for the data pipeline.

Everything that is a judgement call lives here so it can be reviewed and
changed in one place. Nothing in this file is data: it only says where to
download from and how to label what was downloaded.
"""
import os
from pathlib import Path

# QC_ROOT lets the tests point the pipeline at a temporary directory.
ROOT = Path(os.environ.get("QC_ROOT", Path(__file__).resolve().parent.parent))
RAW = ROOT / "raw"
CLEAN = ROOT / "data" / "clean"
REPORTS = ROOT / "data" / "reports"
MANIFEST = RAW / "MANIFEST.json"

USER_AGENT = (
    "QatarCampus-data-pipeline/0.1 (public-records research; "
    + os.environ.get("GITHUB_REPOSITORY", "local-run")
    + ")"
)

# --- Featured countries -----------------------------------------------------
# "lda_code" is the ISO code used by the LDA API (confirmed against
# https://lda.gov/api/v1/constants/general/countries/ on 2026-11-16).
# "fara_values" are the exact strings, upper-cased, that count as this
# country in FARA's "Country/Location Represented" column. Anything not
# listed here is NOT folded into a featured country. Hong Kong, Macau and
# Taiwan are deliberately kept separate, as filed.
FEATURED = {
    "QA": {"name": "Qatar", "fara_values": ["QATAR"]},
    "CN": {"name": "China", "fara_values": ["CHINA"]},
    "RU": {"name": "Russia", "fara_values": ["RUSSIA"]},
    "SA": {"name": "Saudi Arabia", "fara_values": ["SAUDI ARABIA"]},
    "TR": {"name": "Turkey", "fara_values": ["TURKEY", "TURKIYE", "TÜRKIYE"]},
}

# Any FARA country string containing one of these fragments is listed in
# data/reports/fara_country_review.json with its row count and whether it
# was mapped, so a human can check nothing was missed or wrongly merged.
FARA_REVIEW_FRAGMENTS = [
    "QATAR", "CHIN", "RUSS", "SOVIET", "USSR", "SAUDI", "TURK", "TÜRK",
    "HONG KONG", "MACA", "TAIWAN",
]

# "all" keeps every country in the FARA bulk file in the database.
# "featured" keeps only the five featured countries.
FARA_SCOPE = "all"

# --- FARA -------------------------------------------------------------------
FARA_BULK = {
    "registrants": "https://efile.fara.gov/bulk/zip/FARA_All_Registrants.csv.zip",
    "foreign_principals": "https://efile.fara.gov/bulk/zip/FARA_All_ForeignPrincipals.csv.zip",
    "registrant_docs": "https://efile.fara.gov/bulk/zip/FARA_All_RegistrantDocs.csv.zip",
    "short_forms": "https://efile.fara.gov/bulk/zip/FARA_All_ShortForms.csv.zip",
}
FARA_ENCODING = "iso-8859-1"  # stated on the DOJ bulk data page
# Official DOJ listing of every document filed under one registration number.
# Used only as a fallback link when no exhibit names the foreign principal.
FARA_DOC_LISTING = "https://efile.fara.gov/api/v1/RegDocs/html/{regnum}"

# --- LDA --------------------------------------------------------------------
LDA_API = "https://lda.gov/api/v1/filings/"
LDA_PAGE_SIZE = 25
# Each filter is queried once per featured country code. The first four were
# confirmed to work on 2026-11-16. The fetcher verifies every filter before
# trusting it (see fetch_lda.py) and records any it had to skip.
LDA_FILTERS = [
    "client_country",
    "client_ppb_country",
    "foreign_entity_country",
    "affiliated_organization_country",
    "foreign_entity_ppb_country",
    "affiliated_organization_ppb_country",
]
LDA_SLEEP_WITH_KEY = 0.6   # 120 requests/minute allowed with a key
LDA_SLEEP_ANON = 4.2       # 15 requests/minute allowed anonymously

# --- Section 117 ------------------------------------------------------------
# Last complete spreadsheet published on fsapartners.ed.gov (records reported
# through 2025-02-28). Later data lives on ForeignFundingHigherEd.gov; its
# download address is not confirmed yet and is deliberately not guessed here.
SEC117_FILES = {
    "complete_through_2025-02-28": "https://fsapartners.ed.gov/sites/default/files/2025-05/Sec117PublicRecordsCompleteFeb2025.xlsx",
}

# --- Validation -------------------------------------------------------------
# A record whose source link is not on one of these hosts fails the build.
ALLOWED_SOURCE_HOSTS = {
    "efile.fara.gov",
    "lda.gov",
    "fsapartners.ed.gov",
    "www.foreignfundinghighered.gov",
    "www.fec.gov",
}
