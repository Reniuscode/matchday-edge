"""Small HTTP helpers (stdlib only) with retries and polite concurrency."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def fetch(url: str, *, retries: int = 4, timeout: int = 30, headers: dict | None = None) -> bytes:
    url = url.replace("http://", "https://", 1) if url.startswith("http://") else url
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:  # 4xx other than 429 will not get better
            last = e
            if e.code in (400, 401, 403, 404):
                raise
        except Exception as e:  # network blips
            last = e
        time.sleep(1.5 * 2 ** attempt)
    raise RuntimeError(f"GET {url} failed: {last}")


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw).decode("utf-8"))


def fetch_text(url: str, **kw) -> str:
    raw = fetch(url, **kw)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def pmap(fn, items, workers: int = 8):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))
