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
CONCURRENCY = 2 
BACKOFF_BASE = 1.5  # seconds

# ───────────────────────── helpers ─────────────────────────

def agency(node: etree._Element) -> str:
    return node.get("AGENCY") or "UNKNOWN"

def parse_metrics(xml: bytes):
    print("[parse_metrics] Attempting to parse XML.")
    if not xml:
        print("[parse_metrics] XML content is empty.")
        return {}
    
    # Log a snippet of the XML content
    try:
        xml_snippet = xml[:1000].decode('utf-8', errors='ignore')
        print(f"[parse_metrics] XML Snippet (first 1000 chars):\n{xml_snippet}")
    except Exception as e_decode:
        print(f"[parse_metrics] Error decoding XML for snippet logging: {e_decode}")

    try:
        root = etree.fromstring(xml)
        if root is None:
            print("[parse_metrics] etree.fromstring returned None.")
            return {}
    except etree.XMLSyntaxError as e:
        print(f"[parse_metrics] XMLSyntaxError: {e}")
        return {}
    
    bucket = {}
    # Look for DIV8 elements with TYPE="SECTION"
    sections = [el for el in root.iter("DIV8") if el.get("TYPE") == "SECTION"]
    print(f"[parse_metrics] Found {len(sections)} DIV8 elements with TYPE='SECTION'.")

    if not sections:
        print("[parse_metrics] No DIV8 elements with TYPE='SECTION' found in XML.")
        # Save problematic XML for inspection if no relevant sections are found
        problem_xml_path = OUTDIR / "problematic_xml_no_div8_sections.xml"
        try:
            with open(problem_xml_path, "wb") as f:
                f.write(xml)
            print(f"[parse_metrics] Saved XML (no DIV8 sections) to {problem_xml_path}")
        except Exception as e_save:
            print(f"[parse_metrics] Could not save problematic XML: {e_save}")
        return {}
        
    for section in sections:
        ag = agency(section)
        bucket.setdefault(ag, 0)
        bucket[ag] += len(WORD.findall(" ".join(section.itertext())))
    
    if not bucket:
        print("[parse_metrics] Bucket is empty after processing sections.")
        return {}
        
    print(f"[parse_metrics] Parsed metrics: {bucket}")
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
    titles = []
    for t in data["titles"]:
        if not t.get("reserved"):
            number = t["number"]
            latest_issue_date = t.get("latest_issue_date")
            titles.append((number, latest_issue_date))
    return titles

# ───────────────────── fetch with retry ─────────────────────
async def get_with_retry(session, url: str):
    print(f"[get_with_retry] Attempting to GET URL: {url}")
    for attempt in range(MAX_RETRIES + 1):
        print(f"[get_with_retry] Attempt {attempt + 1}/{MAX_RETRIES + 1} for {url}")
        try:
            async with session.get(url, headers=HEADERS) as r:
                print(f"[get_with_retry] Response status for {url}: {r.status}")
                r.raise_for_status() # Will raise ClientResponseError for 4xx/5xx
                content = await r.read()
                print(f"[get_with_retry] Successfully read content for {url} (length: {len(content)})")
                return content
        except ClientResponseError as exc:
            print(f"[get_with_retry] ClientResponseError for {url}: Status {exc.status}, Message: {exc.message}")
            if exc.status == 429 and attempt < MAX_RETRIES:
                sleep_for = BACKOFF_BASE * (2 ** attempt) * (1 + random.random() * 0.3)
                print(f"🔄 429 {url} – sleep {sleep_for:.1f}s (retry {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(sleep_for)
                continue
            if exc.status in (404, 429): # Persistent 404 or 429 after retries
                print(f"[get_with_retry] Persistent {exc.status} for {url}. Returning None.")
                return None 
            print(f"[get_with_retry] Unhandled ClientResponseError for {url}. Raising.")
            raise # Re-raise other client errors
        except asyncio.TimeoutError:
            print(f"[get_with_retry] TimeoutError for {url} on attempt {attempt + 1}")
            if attempt < MAX_RETRIES:
                sleep_for = BACKOFF_BASE * (2 ** attempt) # Simplified backoff for timeout
                print(f"🔄 Timeout {url} – sleep {sleep_for:.1f}s (retry {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(sleep_for)
                continue
            print(f"[get_with_retry] Persistent TimeoutError for {url}. Returning None.")
            return None
        except Exception as e:
            print(f"[get_with_retry] Unexpected error for {url}: {type(e).__name__} - {e}")
            if attempt < MAX_RETRIES:
                sleep_for = BACKOFF_BASE * (2 ** attempt)
                print(f"🔄 Unexpected error {url} – sleep {sleep_for:.1f}s (retry {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(sleep_for)
                continue
            return None # Give up after retries on unexpected errors too

    print(f"[get_with_retry] All retries failed for {url}. Returning None.")
    return None


async def fetch_title(session, day: str, title: int):
    url = FULL_XML_URL.format(d=day, t=f"{title:02d}")
    print(f"[fetch_title] Preparing to fetch title {title} for day {day} from URL: {url}")
    raw = await get_with_retry(session, url)
    
    if raw is None:
        print(f"⚠️  [fetch_title] No raw data returned from get_with_retry for {url}. Likely skipped due to errors.")
        return {}
    
    print(f"[fetch_title] Raw data received for {url}, length {len(raw)}. Attempting to parse.")
    try:
        metrics = parse_metrics(raw)
        if not metrics:
            print(f"⚠️  [fetch_title] parse_metrics returned empty for {url}. Content might be non-XML or empty of SECTIONs.")
        return metrics
    except Exception as e: # Catch-all for unexpected errors during parsing
        print(f"⚠️  [fetch_title] Unexpected error during parse_metrics for {url}: {type(e).__name__} - {e}")
        return {}


async def ingest_for_date(session, day: str, titles): # titles is a list of title numbers
    sem = asyncio.Semaphore(CONCURRENCY) 
    async def throttled(t_num): # t_num is just the title number
        async with sem:
            return await fetch_title(session, day, t_num)
    
    pieces = await asyncio.gather(*(throttled(t_num) for t_num in titles))
    combined = {}
    for p in pieces:
        if p: # Ensure p is not None or empty before updating
            combined.update(p)
    return combined


# ───────────────────────── entrypoint ─────────────────────────
async def main(cli_titles):
    connector = aiohttp.TCPConnector(limit=CONCURRENCY) 
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=300)) as s: # Increased to 300s
        
        all_titles_data = cli_titles or await discover_titles(s)
        print("📄 All titles discovered:", all_titles_data)
        
        if not all_titles_data:
            print("No titles discovered. Exiting.")
            return
        
        titles_to_process = all_titles_data # Process all titles
        print(f"Processing all {len(titles_to_process)} discovered titles.")

        metrics = {}
        for title, latest_issue_date_str in titles_to_process: 
            if not latest_issue_date_str:
                print(f"⚠️  No latest issue date found for title {title}, skipping.")
                continue

            try:
                latest_issue_date = date.fromisoformat(latest_issue_date_str)
                day_str = latest_issue_date.isoformat()
            except ValueError:
                print(f"⚠️  Invalid date format for title {title}: {latest_issue_date_str}, skipping.")
                continue
            
            print(f"Requesting data for title {title} on its latest_issue_date: {day_str}")
            
            current_url_for_title = FULL_XML_URL.format(d=day_str, t=f"{title:02d}")
            try:
                title_metrics = await ingest_for_date(s, day_str, [title]) # Pass title as a list
                
                if title_metrics:
                    print(f"✅ Collected {len(title_metrics)} agencies from {day_str} for title {title}")
                    metrics.update(title_metrics)
                else:
                    print(f"⏭️  {day_str} yielded no data for title {title} from {current_url_for_title}. fetch_title returned empty.")
            
            except (aiohttp.client_exceptions.ClientPayloadError, asyncio.exceptions.TimeoutError, aiohttp.ServerDisconnectedError, asyncio.CancelledError) as e: # Added CancelledError
                print(f"⚠️  Network, timeout, or cancellation exception for title {title} on {day_str} ({current_url_for_title}): {e}")
                continue
            except ClientResponseError as e:
                if e.status == 400 and "date is past the title's most recent issue date" in str(e):
                    match = re.search(r"date of (\d{4}-\d{2}-\d{2})", str(e))
                    if match:
                        issue_date_from_error = match.group(1)
                        print(f"⚠️  Skipping {title} for {day_str}. API error for {current_url_for_title} indicates most recent issue date is {issue_date_from_error}.")
                        continue
                print(f"⚠️  ClientResponseError for title {title} on {day_str} ({current_url_for_title}) with status {e.status}: {e}")
                continue
            except Exception as e: 
                print(f"⚠️  An unexpected error occurred for title {title} on {day_str} ({current_url_for_title}): {e}")
                continue

    if metrics:
        OUTDIR.joinpath("snapshot.json").write_text(json.dumps(metrics, indent=2))
        print("📦 snapshot →", OUTDIR / "snapshot.json")
    else:
        print("No metrics collected. snapshot.json not written.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("titles", nargs="*", type=int, 
                    help="Optional explicit title numbers. If provided, latest_issue_date will be today.")
    args = ap.parse_args()

    processed_cli_titles = []
    if args.titles:
        # If specific titles are passed via CLI, we don't have their latest_issue_date from the API.
        # Defaulting to today for CLI-specified titles.
        # This part of the logic might need refinement if CLI titles should also use their API-provided latest_issue_date.
        # For now, it assumes CLI titles should try today.
        today_date_str = date.today().isoformat()
        for title_num in args.titles:
            processed_cli_titles.append((title_num, today_date_str))
        print(f"Running with specified titles, using today ({today_date_str}) as latest_issue_date: {processed_cli_titles}")
    
    asyncio.run(main(processed_cli_titles))
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
