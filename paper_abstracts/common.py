"""HTTP helper with per-host pacing and retries, plus small text utilities."""
import datetime, html, os, re, time, unicodedata
import requests

class ApiFail(Exception):
    """A source stayed unavailable (rate limit / outage) after all retries."""

CONTACT = os.environ.get("CONTACT_EMAIL", "")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "paper-abstract-pipeline/1.0" + (f" (mailto:{CONTACT})" if CONTACT else "")
_last = {}
LOGFILE = None

def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    if LOGFILE:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

def pace(name, gap):
    wait = gap - (time.time() - _last.get(name, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last[name] = time.time()

def fetch(name, url, gap, params=None, headers=None, tries=3, as_json=True, strict=False):
    """GET with pacing. 404 -> None. 429/5xx -> back off and retry; after the last try
    return None (or raise ApiFail if strict=True)."""
    last = None
    for i in range(tries):
        pace(name, gap)
        try:
            r = SESSION.get(url, params=params, headers=headers, timeout=45)
            last = r.status_code
            if r.status_code == 200:
                return r.json() if as_json else r.text
            if r.status_code == 404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + 3 * i * i)
                continue
            break
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
            time.sleep(2 + 2 * i)
    if strict:
        raise ApiFail(f"{name} unavailable ({last}) for {url.split('?')[0]}")
    return None

# ---- text helpers
def ws(s):
    return " ".join((s or "").split())

def ascii_fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()

def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", html.unescape(ascii_fold(t))).strip()

def strip_tags(s):
    return ws(html.unescape(re.sub(r"<[^>]+>", " ", s or "")))
