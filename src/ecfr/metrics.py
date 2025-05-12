# metrics.py
import json, pandas as pd, textstat, hashlib, datetime as dt, difflib
SNAP = json.loads(Path("data/snapshot.json").read_text())

def flesch(ag):                  # readability
    # pretend we cached prose; in demo use word_count to fake sentences
    wc = SNAP[ag]["word_count"]
    return textstat.flesch_reading_ease("word " * wc)

def volatility(ag, prev_wc):     # custom “Regulatory Volatility Index”
    now = SNAP[ag]["word_count"]
    return (abs(now - prev_wc) / max(prev_wc, 1))

def today_metrics(prev_wc=None):
    out = []
    for ag, v in SNAP.items():
        row = {"agency": ag, **v, "readability": flesch(ag)}
        if prev_wc:
            row["rvi"] = volatility(ag, prev_wc.get(ag, 0))
        out.append(row)
    return pd.DataFrame(out)
