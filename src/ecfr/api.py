# api.py
from fastapi import FastAPI
import json, pandas as pd, hashlib, datetime as dt
from metrics import today_metrics

app = FastAPI(title="eCFR‑micro")

@app.get("/agencies")
def list_agencies():
    return list(json.loads(Path("data/snapshot.json").read_text()).keys())

@app.get("/metrics")
def metrics():
    return today_metrics().to_dict(orient="records")

@app.get("/checksum/{agency}")
def checksum(agency: str):
    snap = json.loads(Path("data/snapshot.json").read_text())
    return {"agency": agency, "checksum": snap[agency]["checksum"]}
