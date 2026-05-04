import requests
import pandas as pd
import time
import json

# Assign zone IDs to human-readable names
ISONE_ZONE_IDS = {
    ".Z.MAINE":        "Maine",
    ".Z.NEWHAMPSHIRE": "New Hampshire",
    ".Z.VERMONT":      "Vermont",
    ".Z.CONNECTICUT":  "Connecticut",
    ".Z.RHODEISLAND":  "Rhode Island",
    ".Z.SEMASS":       "Southeast Massachusetts",
    ".Z.WCMASS":       "West/Central Massachusetts",
    ".Z.NEMASSBOST":   "Northeast Massachusetts/Boston",
}

ISONE_ZONE_IDS_NORM = {k.lstrip("."): v for k, v in ISONE_ZONE_IDS.items()}

def normalize_loc(loc: str) -> str:
    return loc.lstrip(".").strip()

# Simple in-memory cache to avoid hammering the API (5-minute TTL)
_cache = {"data": None, "timestamp": 0}

def fetch_live_prices():
    # Return cached data if it's less than 5 minutes old
    if time.time() - _cache["timestamp"] < 300:
        return _cache["data"]

    url = "https://webservices.iso-ne.com/api/v1.1/fiveminutelmp/current/all.json"

    # ISO-NE sometimes prefers the extension in the URL over the Header,
    # but keeping the header is good practice.
    headers = {"Accept": "application/json"}

    response = requests.get(
        url,
        headers=headers,
        auth=("tomflood@college.harvard.edu", "CS32Passkey"),
        timeout=10
    )
    response.raise_for_status()

    data = response.json()
    with open("api_response.json", "w") as f:
        json.dump(data, f, indent=2)
    print("Response saved to api_response.json")

    # Try the two most common root keys for this endpoint
    root = data.get("FiveMinLmps") or data.get("FiveMinLmp")

    if not root:
        # If those fail, print keys to see what ISO-NE is sending today
        print(f"Unexpected JSON structure. Available keys: {list(data.keys())}")
        return pd.DataFrame()

    # Navigate to the list of price entries
    lmps = root.get("FiveMinLmp", [])

    # Ensure it's a list (ISO-NE returns a dict if there's only one entry)
    if isinstance(lmps, dict):
        lmps = [lmps]

    rows = []
    for entry in lmps:
        location_id = entry["Location"]["$"]
        if location_id in ISONE_ZONE_IDS:
            rows.append({
                "zone":  ISONE_ZONE_IDS[location_id],
                "price": float(entry["LmpTotal"]),
            })

    df = pd.DataFrame(rows)

    # Update cache
    _cache["data"] = df
    _cache["timestamp"] = time.time()

    return df

def fetch_historical_prices(hours_back=24):
    """
    Fetch LMP data for the past N hours at hourly intervals.
    Returns a dict of { "HH:MM" : prices_dataframe }
    """
    from datetime import datetime, timedelta
    import time

    snapshots = {}
    now = datetime.now()

    for hours_ago in range(hours_back, 0, -1):
        target_time = now - timedelta(hours=hours_ago)

        # ISO-NE historical endpoint format
        date_str = target_time.strftime("%Y%m%d")
        hour_str = target_time.strftime("%H")

        url = f"https://webservices.iso-ne.com/api/v1.1/hourlylmp/day/{date_str}/hour/{hour_str}/all.json"

        headers = {"Accept": "application/json"}
        response = requests.get(
            url,
            headers=headers,
            auth=("tomflood@college.harvard.edu", "CS32Passkey"),
            timeout=10
        )

        if response.status_code != 200:
            continue

        data = response.json()
        root = data.get("HourlyLmps") or data.get("HourlyLmp")
        if not root:
            continue

        lmps = root.get("HourlyLmp", [])
        if isinstance(lmps, dict):
            lmps = [lmps]

        rows = []
        for entry in lmps:
            location_id = entry["Location"]["$"]
            if location_id in ISONE_ZONE_IDS:
                rows.append({
                    "zone":  ISONE_ZONE_IDS[location_id],
                    "price": float(entry["LmpTotal"]),
                })

        if rows:
            label = target_time.strftime("%I %p")  # e.g. "02 PM"
            snapshots[label] = pd.DataFrame(rows)

        time.sleep(0.3)  # be polite to the API

    return snapshots
