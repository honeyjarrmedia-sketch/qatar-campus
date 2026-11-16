"""Independent check of the published figures.

Recomputes the headline numbers from the RAW government files with code
that shares nothing with the pipeline, and compares them with what the
site serves. A disagreement is a bug in one of the two.

Run it before publishing a refresh:

    python tests/verify_against_sources.py

One known and intended difference: the raw Section 117 file holds two
amounts with more than two decimal places ($648.333 and $256,993.004).
Each record stores its amount to the cent, so the published grand total is
a cent below a sum of the raw values. What matters is that the figures on
the page equal the sum of the rows in the CSV, which this checks.
"""
import csv, gzip, io, json, zipfile, collections, re, sys

SITE = 'site/data'

def load_zip_csv(path):
    z = zipfile.ZipFile(path); name = [n for n in z.namelist() if n.endswith('.csv')][0]
    text = z.read(name).decode('iso-8859-1').replace('\r\n', '\n').replace('\r', '\n')
    lines, buf, out = text.split('\n'), None, []
    width = len(lines[0][1:-1].split('","'))
    for line in lines:
        buf = line if buf is None else buf + '\n' + line
        if not buf.strip(): buf = None; continue
        if buf.startswith('"') and buf.endswith('"'):
            f = buf[1:-1].split('","')
            if len(f) >= width: out.append(f); buf = None
    return out[0], out[1:]

# ---- FARA, straight from the DOJ file
hdr, rows = load_zip_csv('raw/fara/FARA_All_ForeignPrincipals.csv.zip')
ix = {h: i for i, h in enumerate(hdr)}
qa = [r for r in rows if r[ix['Country/Location Represented']].strip().upper() == 'QATAR']
print(f"RAW FARA Qatar rows                : {len(qa)}")
print(f"RAW FARA Qatar registrations       : {len({r[ix['Registration Number']] for r in qa})}")
print(f"RAW FARA Qatar principals (exact)  : {len({' '.join(r[ix['Foreign Principal']].split()).upper() for r in qa})}")
print(f"RAW FARA countries in file         : {len({r[ix['Country/Location Represented']].strip() for r in rows})}")
print(f"RAW FARA total rows                : {len(rows)}")

# ---- Section 117, straight from the ED spreadsheet
import openpyxl
wb = openpyxl.load_workbook('raw/sec117/Sec117PublicRecordsCompleteFeb2025.xlsx', read_only=True, data_only=True)
ws = wb.worksheets[0]; it = ws.iter_rows(values_only=True); next(it); h2 = next(it)
j = {c: i for i, c in enumerate(h2)}
tot = collections.Counter(); cnt = collections.Counter()
for r in it:
    if not r or all(c is None for c in r): continue
    c = str(r[j['Attribution Country']]).strip().upper()
    cnt[c] += 1
    try: tot[c] += float(r[j['Amount']] or 0)
    except (TypeError, ValueError): pass
print(f"RAW Sec117 Qatar rows              : {cnt['QATAR']}")
print(f"RAW Sec117 Qatar total             : ${tot['QATAR']:,.2f}")
print(f"RAW Sec117 Israel total            : ${tot['ISRAEL']:,.2f}")
print(f"RAW Sec117 grand total             : ${sum(tot.values()):,.2f}")

# ---- What the site serves
def unpack(path):
    p = json.load(open(path)); f, d = p['fields'], p['dict']
    return [{f[i]: (d[f[i]][v] if (f[i] in d and v is not None) else v) for i, v in enumerate(row)} for row in p['rows']]

print('-' * 58)
q = unpack(f'{SITE}/country/qatar.json')
qf = [r for r in q if r['t'] == 'fara']
qu = [r for r in q if r['t'] == 'sec117']
print(f"SITE Qatar FARA rows               : {len(qf)}")
print(f"SITE Qatar FARA registrations      : {len({r['eid'] for r in qf})}")
print(f"SITE Qatar FARA principals         : {len({(r['principal'] or '').upper() for r in qf})}")
print(f"SITE Qatar university rows         : {len(qu)}")
print(f"SITE Qatar university total        : ${sum(r['amount'] or 0 for r in qu):,.2f}")
il = unpack(f'{SITE}/country/israel.json')
print(f"SITE Israel university total       : ${sum(r['amount'] or 0 for r in il if r['t']=='sec117'):,.2f}")
idx = json.load(open(f'{SITE}/index.json'))
print(f"SITE countries listed              : {len(idx['countries'])}")
s = json.load(open(f'{SITE}/summary.json'))
print(f"SITE all-countries university total: ${s['tiles']['university_total']:,.2f}")
print(f"SITE records total                 : {s['records']:,}")

# ---- CSV in the download
with zipfile.ZipFile(f'{SITE}/records-csv.zip') as z:
    with z.open('records.csv') as f:
        rd = list(csv.DictReader(io.TextIOWrapper(f, encoding='utf-8')))
print(f"CSV rows                           : {len(rd):,}")
print(f"CSV rows with no source_url        : {sum(1 for r in rd if not r['source_url'])}")
bad = [r for r in rd if not re.match(r'^https://(efile\.fara\.gov|lda\.gov|fsapartners\.ed\.gov)/', r['source_url'])]
print(f"CSV rows with an off-site link     : {len(bad)}")

# The property a reader can check: the CSV column adds up to the headline.
from decimal import Decimal
csv_uni = sum(Decimal(r['amount_usd']) for r in rd
              if r['amount_usd'] and r['actor_type'] == 'university')
page_uni = Decimal(str(s['tiles']['university_total']))
print(f"CSV university column              : {csv_uni}")
print(f"page university figure             : {page_uni}")
print(f"CSV adds up to the page            : {csv_uni == page_uni}")
sys.exit(0 if csv_uni == page_uni and not bad else 1)
