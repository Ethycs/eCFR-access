from fastapi import FastAPI
from pathlib import Path
import json
from ecfr.metrics import today_metrics

SNAP_PATH = Path(__file__).resolve().parents[2] / "data" / "snapshot.json"
SNAP      = json.loads(SNAP_PATH.read_text()) if SNAP_PATH.exists() else {}

app = FastAPI(title="eCFR‑micro")

@app.get("/agencies")
def agencies():
    return list(SNAP)

@app.get("/metrics")
def metrics():
    return today_metrics().to_dict(orient="records")

@app.get("/checksum/{agency}")
def checksum(agency: str):
    return {"agency": agency, "checksum": SNAP.get(agency, {}).get("checksum")}