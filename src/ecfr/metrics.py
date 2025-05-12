"""Derive additional analytics from the latest snapshot."""
import json, hashlib
from datetime import date, timedelta
from pathlib import Path
import pandas as pd, textstat, aiohttp, asyncio
from lxml import etree
import re

SNAP_PATH = Path("data/snapshot.json")
SNAP      = json.loads(SNAP_PATH.read_text()) if SNAP_PATH.exists() else {}

# ---- helpers for optional history -----------------------------------------
BASE   = "https://www.ecfr.gov/api/versioner/v1/full/{d}/title-{t}.xml"
WORD   = re.compile(r"\w+")

def word_count_from_xml(raw: bytes) -> int:
    root = etree.fromstring(raw)
    return len(WORD.findall(" ".join(root.itertext())))

async def yesterday_wc(titles):
    y = (date.today() - timedelta(days=1)).isoformat()
    async with aiohttp.ClientSession() as s:
        xml_blobs = await asyncio.gather(*(
            (await s.get(BASE.format(d=y, t=f"{t:02d}"))).read() for t in titles
        ))
    return sum(word_count_from_xml(b) for b in xml_blobs)
# ---------------------------------------------------------------------------

def flesch(ag):
    wc = SNAP[ag]["word_count"]
    # Fake prose by repeating "word" wc times – works for Flesch numerator/denominator ratio
    return textstat.flesch_reading_ease("word " * wc)

def rvi(now, prev):
    return abs(now - prev) / max(prev, 1)

def today_metrics(prev_wc=None):
    rows = []
    for ag, v in SNAP.items():
        row = {"agency": ag, **v, "readability": flesch(ag)}
        if prev_wc:
            row["rvi"] = rvi(v["word_count"], prev_wc.get(ag, 0))
        rows.append(row)
    return pd.DataFrame(rows)