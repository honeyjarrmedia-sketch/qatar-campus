# Qatar Campus data pipeline

Builds a dataset of foreign-principal relationships and lobbying filings from
official US public records. Every record links to the government document it
came from. Nothing is estimated: a field with no source is left empty.

## Layout

| Path | What it holds |
|---|---|
| `raw/` | Files exactly as downloaded, plus `MANIFEST.json` (address, time, SHA-256 of each) |
| `data/clean/` | The published dataset, regenerated from `raw/` |
| `data/reports/` | Review reports: skipped rows, country spellings, link check, validation |
| `pipeline/` | Download, cleaning, validation, link-check and site-build code |
| `web/` | The page template, stylesheet and script |
| `site/` | The finished one-page site, rebuilt from `data/clean/`. This is the folder Cloudflare Pages serves |
| `site.config.json` | Brand name, site address, corrections contact, change log and commentary text |
| `tests/` | Tests. Their fixtures are synthetic and never enter `data/` |

## Quarterly update

1. On GitHub, open **Actions → Refresh data → Run workflow**.
2. The job downloads the raw files, rebuilds the dataset, checks links and
   pushes everything to a new branch named `data/refresh-<date>`.
3. Open the compare link in the job summary and review what changed.
4. Merge the branch to publish.

To run locally instead:

```
pip install -r requirements.txt
python -m pipeline.run fetch
python -m pipeline.run clean
python -m pipeline.run fees --country QA   # after statements are downloaded
python -m pipeline.run site
python -m pipeline.run check-links
```

An LDA API key is optional (free at https://lda.gov/api/register/). Without
one the LDA download is slower. Set it as the `LDA_API_KEY` secret or
environment variable.

## Sources

| Source | Address | Notes |
|---|---|---|
| DOJ FARA bulk data | `https://efile.fara.gov/bulk/zip/` | Four zipped CSV files, ISO-8859-1. No dollar amounts |
| LDA filings | `https://lda.gov/api/v1/filings/` | Queried per featured country; raw JSON kept per filing |
| Section 117 | `fsapartners.ed.gov` spreadsheet | University gifts and contracts, every country, reported through 2025-02-28 |
| FARA supplemental statements | `efile.fara.gov` PDFs | Item 14(a) payment figures. Several GB, so the workflow reads and discards them |

Senate Office of Public Records cannot vouch for the data or analyses derived
from these data after the data have been retrieved from LDA.gov.

## Rules the code enforces

- A record with no source link, or a link outside the official hosts in
  `pipeline/config.py`, fails the build.
- If a FARA file's columns differ from the expected ones, the build stops and
  prints the columns it found.
- Rows that cannot be parsed are skipped and counted in `data/reports/`.
- Country is kept as filed. Hong Kong, Macau and Taiwan are not merged into
  China. Every FARA country spelling near a featured country is listed in
  `data/reports/fara_country_review.json`.
- A country on an LDA record is where the client or a listed entity is
  located. It does not mean the filing involves that country's government.

## Confidence flags

- `verified`: the record matches one official document, which it links to.
- `derived`: computed from several records; the method is stated.
- `partial`: the source has a known gap. For FARA this means no exhibit
  naming the foreign principal was found, so the link lists all documents
  filed under that registration number.

## Method notes

- **FARA record**: one per registrant and foreign principal, from the DOJ
  foreign principals file. Dates are the relationship's start and end as
  listed. `amount_usd` is always empty because the bulk data has no amounts.
- **LDA record**: one per filing per featured country. `link_basis` states
  which line of the filing ties it to the country.
- **Amended LDA reports**: for the same registrant, client, year and period,
  the most recently posted report is used in totals; earlier ones are kept
  and marked `superseded`.
- **Connections**: the same FARA registration number or LDA registrant ID has
  records in two or more featured countries. Names are never matched across
  sources automatically; identical names are listed for review in
  `data/reports/possible_same_entity.json`.

## The site

One static page, no build tooling: `python -m pipeline.run site` writes
`site/` from `data/clean/` and `web/`. The default view (Qatar, all years) is
written into the HTML, so the page has real content before any script runs.

Each country is its own file under `site/data/country/`, fetched when that
country is chosen, so the page opens with Qatar alone (about half a megabyte)
however large the dataset grows. `site/data/index.json` lists the countries,
`summary.json` holds the totals and year series behind the "All countries"
view, and `entity_countries.json` says which country files hold a given
organisation's records.

Cloudflare Pages settings: build command empty, output directory `site`.

To preview the layout with invented data (never written into this repository):

```
QC_ROOT=/tmp/qc-demo python tests/make_demo_site.py
python -m http.server --directory /tmp/qc-demo/site 8000
```
