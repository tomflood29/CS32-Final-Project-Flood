import requests
import pandas as pd
import time

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

# Simple in-memory cache to avoid hammering the API (5-minute TTL)
_cache = {"data": None, "timestamp": 0}

def fetch_live_prices():
    # Return cached data if it's less than 5 minutes old
    if time.time() - _cache["timestamp"] < 300:
        return _cache["data"]

    url = "https://webservices.iso-ne.com/api/v1.1/realtimelbmp/current"
    headers = {"Accept": "application/json"}

    response = requests.get(
        url,
        headers=headers,
        auth=("tomflood@college.harvard.edu", "CS32Passkey"),
        timeout=10
    )
    response.raise_for_status()

    data = response.json()

    # Navigate nested response structure
    lmps = data["RtLbmp"]["RtLbmps"]["RtLbmp"]

    # If only one zone is returned, the API gives a dict instead of a list
    if isinstance(lmps, dict):
        lmps = [lmps]

    rows = []
    for entry in lmps:
        location_id = entry["Location"]["@LocId"]
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
