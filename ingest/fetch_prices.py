"""Fetch today's mandi prices from data.gov.in (AGMARKNET) and save a dated CSV snapshot.

The API only returns the current day's prices, so running this daily is how
Mandi Pulse builds its price history.

The API refuses offsets past 10,000 records, so on busy days (total > 10,000)
we discover the states present and then fetch each state separately.
"""
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
PAGE_SIZE = 1000
RESULT_WINDOW = 10_000  # API hard limit on offset + limit
# The API stalls on the default python-requests User-Agent, so send our own.
HEADERS = {"User-Agent": "mandi-pulse/0.1 (+https://github.com/atmika1807/mandi-pulse)"}
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def fetch_page(api_key: str, offset: int, state: str | None = None, retries: int = 3) -> dict:
    params = {"api-key": api_key, "format": "json", "limit": PAGE_SIZE, "offset": offset}
    if state:
        params["filters[state.keyword]"] = state
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            print(f"state={state} offset={offset} attempt {attempt} failed: {err}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"Giving up on state={state} offset={offset}")


def fetch_paginated(api_key: str, state: str | None = None) -> tuple[list[dict], int]:
    first = fetch_page(api_key, 0, state)
    total = int(first.get("total", 0))
    records = first.get("records", [])
    for offset in range(PAGE_SIZE, min(total, RESULT_WINDOW), PAGE_SIZE):
        records.extend(fetch_page(api_key, offset, state).get("records", []))
    return records, total


def fetch_all(api_key: str) -> pd.DataFrame:
    records, total = fetch_paginated(api_key)
    print(f"API reports {total} records for today")
    if total <= RESULT_WINDOW:
        return pd.DataFrame(records)

    states = sorted({r["state"] for r in records})
    print(f"Over {RESULT_WINDOW} records; fetching {len(states)} states separately")
    records = []
    for state in states:
        state_records, state_total = fetch_paginated(api_key, state)
        records.extend(state_records)
        print(f"  {state}: {len(state_records)}/{state_total}")

    if len(records) < total:
        print(f"WARNING: got {len(records)} of {total} records; some states may be missing")
    return pd.DataFrame(records)


def main() -> None:
    load_dotenv()
    api_key = os.getenv("DATA_GOV_API_KEY")
    if not api_key:
        sys.exit("DATA_GOV_API_KEY not set. Add it to .env (local) or GitHub Secrets (Actions).")

    df = fetch_all(api_key)
    if df.empty:
        sys.exit("No records returned; not writing a file.")

    df["fetched_on"] = date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"mandi_prices_{date.today().isoformat()}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")


if __name__ == "__main__":
    main()
