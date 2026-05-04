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
        location_id = normalize_loc(entry["Location"]["$"])
        if location_id in ISONE_ZONE_IDS_NORM:
            rows.append({
                "zone": ISONE_ZONE_IDS_NORM[location_id],
                "price": float(entry["LmpTotal"]),
            })

    df = pd.DataFrame(rows)

    # Update cache
    _cache["data"] = df
    _cache["timestamp"] = time.time()

    return df

def fetch_historical_prices(hours_back=24):
    """
    Fetch RT Preliminary Hourly LMP data for the past N hours.
    Returns a dict of { "YYYY-MM-DD HH:00" : prices_dataframe }
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import time
    import pandas as pd
    import requests

    tz = ZoneInfo("America/New_York")  # ISO-NE is Eastern
    end = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours_back)

    # The exact hours we want snapshots for (last 24 full hours)
    wanted_hours = [start + timedelta(hours=i) for i in range(hours_back)]
    wanted_labels = {dt.strftime("%Y-%m-%d %H:00") for dt in wanted_hours}

    # Only need to query the days that appear in the window
    needed_days = sorted({dt.strftime("%Y%m%d") for dt in wanted_hours})

    # label -> {zone -> price}
    prices_by_label = {dt.strftime("%Y-%m-%d %H:00"): {} for dt in wanted_hours}

    session = requests.Session()
    headers = {"Accept": "application/json"}

    for location_id, zone_name in ISONE_ZONE_IDS.items():
        for day_str in needed_days:
            url = (
                "https://webservices.iso-ne.com/api/v1.1/"
                f"hourlylmp/rt/prelim/day/{day_str}/location/{location_id}.json"
            )

            try:
                r = session.get(
                    url,
                    headers=headers,
                    auth=("tomflood@college.harvard.edu", "CS32Passkey"),
                    timeout=(5, 45),  # (connect timeout, read timeout)
                )
                if r.status_code != 200:
                    print("Hourly failed:", r.status_code, url)
                    continue
                data = r.json()
            except requests.exceptions.ReadTimeout:
                print("Hourly timed out:", url)
                continue
            except requests.exceptions.RequestException as e:
                print("Hourly request error:", e, url)
                continue

            root = data.get("HourlyLmps") or data.get("HourlyLmp")
            if not root:
                continue

            lmps = root.get("HourlyLmp", [])
            if isinstance(lmps, dict):
                lmps = [lmps]

            for entry in lmps:
                begin = entry.get("BeginDate")
                if not begin:
                    continue

                # ISO-NE BeginDate is a dateTime; parse and convert to Eastern
                dt = datetime.fromisoformat(begin.replace("Z", "+00:00")).astimezone(tz)
                label = dt.strftime("%Y-%m-%d %H:00")

                if label in wanted_labels:
                    try:
                        prices_by_label[label][zone_name] = float(entry["LmpTotal"])
                    except (KeyError, TypeError, ValueError):
                        pass

            time.sleep(0.15)  # be polite

    # Convert to the exact structure your map expects
    snapshots = {}
    for label, zone_to_price in prices_by_label.items():
        if zone_to_price:
            snapshots[label] = pd.DataFrame(
                [{"zone": z, "price": p} for z, p in zone_to_price.items()]
            )

    return snapshots
