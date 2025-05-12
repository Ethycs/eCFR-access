from fastapi import FastAPI
from pathlib import Path
import json, pandas as pd
from metrics import today_metrics

app = FastAPI(title="eCFR‑micro")
SNAP_PATH = Path("data/snapshot.json")
SNAP      = json.loads(SNAP_PATH.read_text()) if SNAP_PATH.exists() else {}

@app.get("/agencies")
def agencies():
    return list(SNAP.keys())

@app.get("/metrics")
def metrics():
    return today_metrics().to_dict(orient="records")

@app.get("/checksum/{agency}")
def checksum(agency: str):
    return {"agency": agency, "checksum": SNAP.get(agency, {}).get("checksum", None)}