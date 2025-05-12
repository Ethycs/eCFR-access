from __future__ import annotations
"""Download current CFR titles from the eCFR v1 API, respecting rate limits.

* Early‑stop tolerant: after max retries, persistent 429/404 titles are skipped.
* Concurrency capped to 5; exponential back‑off on 429.
"""


import argparse, asyncio, hashlib, json, random, re, sys
from datetime import date, timedelta
from pathlib import Path

import aiohttp
from aiohttp import ClientResponseError
from lxml import etree

WORD = re.compile(r"\w+")
OUTDIR = Path(__file__).resolve().parents[2] / "data"
OUTDIR.mkdir(exist_ok=True)

TITLE_LIST_URL = "https://www.ecfr.gov/api/versioner/v1/titles"
FULL_XML_URL = "https://www.ecfr.gov/api/versioner/v1/full/{d}/title-{t}.xml"
HEADERS = {"User-Agent": "ecfr-micro/0.6"}
MAX_RETRIES = 4
CONCURRENCY = 5
BACKOFF_BASE = 1.5  # seconds

# ───────────────────────── helpers ─────────────────────────

def agency(node: etree._Element) -> str:
    return node.get("AGENCY") or "UNKNOWN"

def parse_metrics(xml: bytes):
    root, bucket = etree.fromstring(xml), {}
    for section in root.iter("SECTION"):
        ag = agency(section)
        bucket.setdefault(ag, 0)
        bucket[ag] += len(WORD.findall(" ".join(section.itertext())))
    return {
        ag: {
            "word_count": wc,
            "checksum": hashlib.sha256(f"{ag}{wc}".encode()).hexdigest(),
        }
        for ag, wc in bucket.items()
    }

async def discover_titles(session):
    async with session.get(TITLE_LIST_URL, headers=HEADERS) as r:
        data = await r.json()
    return [t["number"] for t in data["titles"] if not t.get("reserved")]

# ───────────────────── fetch with retry ─────────────────────
async def get_with_retry(session, url: str):
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.get(url, headers=HEADERS) as r:
                r.raise_for_status()
                return await r.read()
        except ClientResponseError as exc:
            if exc.status == 429 and attempt < MAX_RETRIES:
                sleep_for = BACKOFF_BASE * (2 ** attempt) * (1 + random.random() * 0.3)
                print(f"🔄 429 {url} – sleep {sleep_for:.1f}s (retry {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(sleep_for)
                continue
            if exc.status in (404, 429):
                return None  # skip after retries
            raise

async def fetch_title(session, day: str, title: int):
    url = FULL_XML_URL.format(d=day, t=f"{title:02d}")
    raw = await get_with_retry(session, url)
    if raw is None:
        print(f"⚠️  skipped {url}")
        return {}
    try:
        return parse_metrics(raw)
    except etree.XMLSyntaxError:
        print(f"⚠️  bad XML {url}")
        return {}

async def ingest_for_date(session, day: str, titles):
    sem = asyncio.Semaphore(CONCURRENCY)
    async def throttled(t):
        async with sem:
            return await fetch_title(session, day, t)
    pieces = await asyncio.gather(*(throttled(t) for t in titles))
    combined = {}
    for p in pieces:
        combined.update(p)
    return combined

# ───────────────────────── entrypoint ─────────────────────────
async def main(cli_titles):
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector) as s:
        titles = cli_titles or await discover_titles(s)
        print("📄 titles:", titles)
        today = date.today()
        for offset in range(6):
            day = (today - timedelta(days=offset)).isoformat()
            metrics = await ingest_for_date(s, day, titles)
            if metrics:
                print(f"✅ collected {len(metrics)} agencies from {day}")
                break
            print(f"⏭️  {day} yielded no data – back one more day")
        else:
            print("❌ no data after 5 days")
            sys.exit(1)
    OUTDIR.joinpath("snapshot.json").write_text(json.dumps(metrics, indent=2))
    print("📦 snapshot →", OUTDIR / "snapshot.json")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("titles", nargs="*", type=int)
    asyncio.run(main(ap.parse_args().titles))
"""Download *all current* CFR titles via the eCFR v1 API and write a per‑agency
metric snapshot (`data/snapshot.json`).

Key features
------------
* Title discovery via `/api/versioner/v1/titles` (skips reserved).
* **Concurrency capped to 5** with `aiohttp.TCPConnector(limit=5)` to stay under
  the 60 req/min service guideline.
* **Exponential back‑off** on HTTP 429 (Too Many Requests) up to 4 retries.
* Falls back up to **5 days** if today’s XML isn’t published yet.

CLI usage:
    python ingest_api.py            # auto‑discover and fetch
    python ingest_api.py 14 21      # fetch only specific titles
"""


import argparse, asyncio, hashlib, json, re, sys, random, math
from datetime import date, timedelta
from pathlib import Path

import aiohttp
from aiohttp import ClientResponseError
from lxml import etree

# ---------------------------- constants --------------------------------------
WORD   = re.compile(r"\w+")
OUTDIR = Path(__file__).resolve().parents[2] / "data"
OUTDIR.mkdir(exist_ok=True)

TITLE_LIST_URL = "https://www.ecfr.gov/api/versioner/v1/titles"
FULL_XML_URL   = "https://www.ecfr.gov/api/versioner/v1/full/{d}/title-{t}.xml"
HEADERS        = {"User-Agent": "ecfr-micro/0.5"}
MAX_RETRIES    = 4      # on 429
CONCURRENCY    = 5      # eCFR suggests ≤ 60 req/min, so 5 concurrent is safe
BACKOFF_BASE   = 1.5    # seconds

# ---------------------------- helpers ----------------------------------------

def agency(node: etree._Element) -> str:
    """Return AGENCY attr or fallback."""
    return node.get("AGENCY") or "UNKNOWN"

def parse_metrics(xml: bytes) -> dict[str, dict]:
    root, bucket = etree.fromstring(xml), {}
    for section in root.iter("SECTION"):
        ag = agency(section)
        words = WORD.findall(" ".join(section.itertext()))
        bucket.setdefault(ag, []).append(len(words))
    return {
        ag: {
            "word_count": sum(lst),
            "checksum": hashlib.sha256("".join(map(str, lst)).encode()).hexdigest(),
        }
        for ag, lst in bucket.items()
    }

async def discover_titles(session: aiohttp.ClientSession) -> list[int]:
    async with session.get(TITLE_LIST_URL, headers=HEADERS) as r:
        data = await r.json()
    return [t["number"] for t in data["titles"] if not t.get("reserved")]

# ---------------------------- fetch with retry -------------------------------
async def get_with_retry(session: aiohttp.ClientSession, url: str) -> bytes | None:
    """GET with exponential back‑off on 429."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with session.get(url, headers=HEADERS) as r:
                r.raise_for_status()
                return await r.read()
        except ClientResponseError as exc:
            if exc.status == 429 and attempt < MAX_RETRIES:
                sleep_for = BACKOFF_BASE * (2 ** attempt) * (1 + random.random() * 0.2)
                print(f"🔄 429 on {url} – sleeping {sleep_for:.1f}s (retry {attempt+1})")
                await asyncio.sleep(sleep_for)
                continue
            if exc.status == 404:
                return None
            raise

async def fetch_title(session: aiohttp.ClientSession, day: str, title: int) -> dict:
    url = FULL_XML_URL.format(d=day, t=f"{title:02d}")
    raw = await get_with_retry(session, url)
    if raw is None:
        print(f"⚠️  404 {url}")
        return {}
    try:
        return parse_metrics(raw)
    except etree.XMLSyntaxError:
        print(f"⚠️  invalid XML {url}")
        return {}

async def ingest_for_date(session: aiohttp.ClientSession, day: str, titles: list[int]) -> dict:
    sem = asyncio.Semaphore(CONCURRENCY)
    async def throttled(title: int):
        async with sem:
            return await fetch_title(session, day, title)
    parts = await asyncio.gather(*(throttled(t) for t in titles))
    combined: dict[str, dict] = {}
    for part in parts:
        combined.update(part)
    return combined

# ---------------------------- entrypoint -------------------------------------
async def main(cli_titles: list[int]):
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector, raise_for_status=True) as s:
        titles = cli_titles or await discover_titles(s)
        print("📄  titles today:", titles)

        today = date.today()
        for offset in range(0, 6):  # today … 5 days back
            day = today - timedelta(days=offset)
            combined = await ingest_for_date(s, day.isoformat(), titles)
            if combined:
                print(f"✅  fetched {len(combined)} agencies from {day.isoformat()}")
                break
            print(f"⏭️  {day.isoformat()} empty – stepping back a day")
        else:
            print("❌  no data found in last 5 days", file=sys.stderr)
            sys.exit(1)

    OUTDIR.joinpath("snapshot.json").write_text(json.dumps(combined, indent=2))
    print("📦  snapshot saved →", OUTDIR / "snapshot.json")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("titles", nargs="*", type=int, help="Optional explicit title numbers")
    asyncio.run(main(p.parse_args().titles))