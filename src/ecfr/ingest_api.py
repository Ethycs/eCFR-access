# ingest_api.py
"""
Grab today’s eCFR XML for a small set of titles via the official
eCFR v1 API and write one JSON blob containing per‑agency metrics.

Run:
    python ingest_api.py               # defaults to titles 1‑3
    python ingest_api.py 1 5 12 50     # any list you want
"""
import asyncio, aiohttp, argparse, json, re, hashlib
from datetime import date
from pathlib import Path
from lxml import etree

BASE   = "https://www.ecfr.gov/api/versioner/v1/full/{d}/title-{t}.xml"
TODAY  = date.today().isoformat()
OUTDIR = Path("data"); OUTDIR.mkdir(exist_ok=True)

WORD   = re.compile(r"\w+")

def agency(node: etree._Element) -> str:
    """AGENCY attribute exists only at SECTION level; fall back to 'UNKNOWN'."""
    return node.get("AGENCY") or "UNKNOWN"

def parse_metrics(xml_bytes: bytes) -> dict:
    root, bucket = etree.fromstring(xml_bytes), {}
    for section in root.iter("SECTION"):
        ag = agency(section)
        words = WORD.findall(" ".join(section.itertext()))
        bucket.setdefault(ag, []).append(len(words))
    # aggregate to agency‑level metrics
    return {
        ag: {
            "word_count": sum(lst),
            "checksum": hashlib.sha256("".join(map(str,lst)).encode()).hexdigest()
        }
        for ag, lst in bucket.items()
    }

async def fetch_title(session, title):
    url = BASE.format(d=TODAY, t=f"{title:02d}")
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.read()

async def main(titles):
    async with aiohttp.ClientSession() as s:
        xml_blobs = await asyncio.gather(*(fetch_title(s, t) for t in titles))
    metrics = {}
    for blob in xml_blobs:
        metrics.update(parse_metrics(blob))
    OUTDIR.joinpath("snapshot.json").write_text(json.dumps(metrics))
    print("✅ metrics written → data/snapshot.json")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("titles", nargs="*", type=int, default=[1,2,3],
                   help="Title numbers to pull (default 1‑3)")
    asyncio.run(main(p.parse_args().titles))
