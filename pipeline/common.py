"""Small shared helpers: files, hashing, HTTP, text normalisation."""
import datetime as dt
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request

from . import config


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=False)
        f.write("\n")


def write_json_rows(path, rows: list) -> None:
    """A JSON array with one record per line: valid JSON, compact, and each
    changed record shows as one changed line when versions are compared."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, r in enumerate(rows):
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            f.write(",\n" if i < len(rows) - 1 else "\n")
        f.write("]\n")


def update_manifest(source: str, entries: list) -> None:
    """Replace one source's section of raw/MANIFEST.json."""
    manifest = read_json(config.MANIFEST, {}) or {}
    manifest[source] = entries
    write_json(config.MANIFEST, manifest)


def http_get(url: str, headers: dict | None = None, timeout: int = 120,
             retries: int = 4) -> bytes:
    """GET with a descriptive User-Agent, retries and Retry-After support."""
    hdrs = {"User-Agent": config.USER_AGENT, "Accept": "*/*"}
    hdrs.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 30)
                time.sleep(min(wait, 300) + 1)
                continue
            if e.code in (500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def norm_name(name: str) -> str:
    """Normalise a name for exact-match comparison only (never fuzzy)."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slugify(text: str, max_len: int = 70) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:max_len].strip("-") or "unnamed"


_LOWER_WORDS = {"of", "and", "the", "da", "de", "du"}


def title_country(raw: str) -> str:
    """Display form of an upper-case country string. Formatting only."""
    words = (raw or "").strip().lower().split(" ")
    out = []
    for i, w in enumerate(words):
        if i and w in _LOWER_WORDS:
            out.append(w)
        else:
            out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    return " ".join(out)


def parse_mdy(value: str):
    """MM/DD/YYYY -> YYYY-MM-DD. Returns None if empty or unparseable."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        return dt.datetime.strptime(v, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None
