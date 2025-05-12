"""
Download one or more CFR Titles via the official eCFR v1 API
and write a JSON snapshot with per‑agency metrics.

   python ingest_api.py            # titles 1‑3 for a quick demo
   python ingest_api.py 1 5 12 50  # any list you want
"""
import argparse, asyncio, aiohttp, hashlib, json, re
from datetime import date
from pathlib import Path
from lxml import etree

BASE   = "https://www.ecfr.gov/api/versioner/v1/full/{d}/title-{t}.xml"
TODAY  = date.today().isoformat()
OUTDIR = Path("data"); OUTDIR.mkdir(exist_ok=True)

WORD = re.compile(r"\w+")

def agency(node: etree._Element) -> str:
    """Return SECTION's AGENCY attr or fallback."""
    return node.get("AGENCY") or "UNKNOWN"

def is_xml(blob: bytes) -> bool:
    """Cross‑platform XML validity test (no python‑magic‑bin)."""
    try:
        etree.fromstring(blob)
        return True
    except etree.XMLSyntaxError:
        return False

def parse_metrics(xml_bytes: bytes) -> dict:
    root, bucket = etree.fromstring(xml_bytes), {}
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

async def fetch_title(session: aiohttp.ClientSession, title: int) -> bytes:
    url = BASE.format(d=TODAY, t=f"{title:02d}")
    async with session.get(url) as r:
        r.raise_for_status()
        raw = await r.read()
    if not is_xml(raw):
        raise ValueError(f"{url} did not return valid XML")
    return raw

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
    p.add_argument("titles", nargs="*", type=int, default=[1, 2, 3],
                   help="Title numbers to pull (default 1‑3)")
    asyncio.run(main(p.parse_args().titles))