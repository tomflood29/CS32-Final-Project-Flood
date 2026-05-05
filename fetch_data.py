import time
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd


# Zone "codes" (what you see in Location["$"]) -> human readable names
ISONE_ZONES = {
    ".Z.MAINE":        "Maine",
    ".Z.NEWHAMPSHIRE": "New Hampshire",
    ".Z.VERMONT":      "Vermont",
    ".Z.CONNECTICUT":  "Connecticut",
    ".Z.RHODEISLAND":  "Rhode Island",
    ".Z.SEMASS":       "Southeast Massachusetts",
    ".Z.WCMASS":       "West/Central Massachusetts",
    ".Z.NEMASSBOST":   "Northeast Massachusetts/Boston",
}


BASE = "https://webservices.iso-ne.com/api/v1.1"

_session = requests.Session()

# Cache live prices (5 min) and LocId mapping (1 hour) - so that not constantly requesting from API
_live_cache = {"data": None, "ts": 0}
_locid_cache = {"data": None, "ts": 0}


def _get(url: str, timeout=(5, 45)) -> requests.Response:
    return _session.get(
        url,
        headers={"Accept": "application/json"},
        auth=("tomflood@college.harvard.edu", "CS32Passkey"),
        timeout=timeout,
    )#opens a session so that the website can update to live prices each time


def fetch_zone_locids(force_refresh=False) -> dict:
    """
    returns zone ID "z.MAINE" with its nuemeric ID. Need numeric for historical prices
      entry["Location"]["$"]      -> '.Z.MAINE'
      entry["Location"]["@LocId"] -> numeric id required by /hourlylmp/.../location/{locationId}
    """
    if (not force_refresh) and (time.time() - _locid_cache["ts"] < 3600) and _locid_cache["data"]:
        return _locid_cache["data"] #if data less than an hour old, don't call on API request, just use cache

    url = f"{BASE}/fiveminutelmp/current/all.json"
    r = _get(url, timeout=(5, 45))
    r.raise_for_status() #if error - 404 etc, returns error message
    data = r.json()

    root = data.get("FiveMinLmps") or data.get("FiveMinLmp") #checks that data["Key"] exists - returns error if not.
    if not root:
        raise RuntimeError(f"Unexpected JSON structure for fiveminutelmp. Top keys: {list(data.keys())}")

    lmps = root.get("FiveMinLmp", [])
    if isinstance(lmps, dict): # where API returns dictionary, rather than list, this turns it into a list so for loop works.
        lmps = [lmps]

    zone_to_locid = {}
    for entry in lmps:
        loc = entry.get("Location", {})
        zone_code = loc.get("$")          # '.Z.MAINE'
        locid = loc.get("@LocId")         # numeric id

        if zone_code in ISONE_ZONES and locid is not None: #if in zone, turns to str then saves to cache later
            zone_to_locid[zone_code] = str(locid)

    if not zone_to_locid:
        raise RuntimeError("No LocIds for zones.") #de-bugging - check if there are any IDs

    _locid_cache["data"] = zone_to_locid
    _locid_cache["ts"] = time.time()
    return zone_to_locid


def fetch_live_prices():
    """Fetch latest 5-minute LMPs for your zones."""
    if time.time() - _live_cache["ts"] < 300 and _live_cache["data"] is not None:
        return _live_cache["data"] #checks if last updated less than 5 mins ago - uses cache if so

    url = f"{BASE}/fiveminutelmp/current/all.json"
    r = _get(url, timeout=(5, 45))
    r.raise_for_status()

    data = r.json()
    with open("api_response.json", "w") as f:
        json.dump(data, f, indent=2)
    print("Response saved to api_response.json") #really helpful with debugging - most useful visual

    root = data.get("FiveMinLmps") or data.get("FiveMinLmp") # similar to before, checking keys
    if not root:
        print(f"Unexpected JSON structure. Available keys: {list(data.keys())}")
        return pd.DataFrame(columns=["zone", "price"])

    lmps = root.get("FiveMinLmp", [])
    if isinstance(lmps, dict):
        lmps = [lmps]

    rows = []
    for entry in lmps:
        loc = entry.get("Location", {})
        zone_code = loc.get("$")  # e.g. '.Z.MAINE'
        if zone_code in ISONE_ZONES:
            rows.append({
                "zone": ISONE_ZONES[zone_code],
                "price": float(entry["LmpTotal"]),
            })

    df = pd.DataFrame(rows) #creates data frame with pandas so that it can be manipulated in map_viz.py
    _live_cache["data"] = df
    _live_cache["ts"] = time.time()
    return df


def fetch_historical_prices(hours_back=24):
    tz = ZoneInfo("America/New_York")
    end_hour = datetime.now(tz).replace(minute=0, second=0, microsecond=0) #backdates to most recent hour
    start_hour = end_hour - timedelta(hours=hours_back)
    wanted_hours = [start_hour + timedelta(hours=i) for i in range(hours_back)]
    wanted_labels = {dt.strftime("%Y-%m-%d %H:00") for dt in wanted_hours} #put all the past 24 hours in form YYYY-MM-DD TT:00 so can search API for these

    needed_days = sorted({dt.strftime("%Y%m%d") for dt in wanted_hours}) #gets the wanted days

    # Prepare structure label -> dict(zone_name -> price)
    prices_by_label = {dt.strftime("%Y-%m-%d %H:00"): {} for dt in wanted_hours}

    zone_locids = fetch_zone_locids() #need numerical IDs - unlike 5 mins data

    for zone_code, zone_name in ISONE_ZONES.items(): #gets the data for each day and each hour, for each zone 
        locid = zone_locids.get(zone_code)
        if not locid:
            print(f"Missing LocId for {zone_code}; skipping")
            continue

        for day_str in needed_days:
            url = f"{BASE}/hourlylmp/rt/prelim/day/{day_str}/location/{locid}.json"

            try:
                r = _get(url, timeout=(5, 60))
            except requests.exceptions.ReadTimeout: #timeout network error
                print("Hourly timed out:", url)
                continue
            except requests.exceptions.RequestException as e:
                print("Hourly request error:", e, url)
                continue

            if r.status_code != 200: #standard accepted and recieved status code
                print("Hourly failed:", r.status_code, url)
                continue

            data = r.json()
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

                # ISO-NE begin dates are ISO strings; sometimes end with Z
                begin_norm = begin.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(begin_norm)
                except ValueError:
                    continue

                # If timezone missing, assume Eastern; otherwise convert to Eastern
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                else:
                    dt = dt.astimezone(tz)

                label = dt.strftime("%Y-%m-%d %H:00")
                if label in wanted_labels:
                    try:
                        prices_by_label[label][zone_name] = float(entry["LmpTotal"])
                    except (KeyError, TypeError, ValueError):
                        pass

            time.sleep(0.12)  # be polite

    # Convert to the format map_viz3 expects: label -> DataFrame(zone, price)
    snapshots = {}
    for label, zone_to_price in prices_by_label.items():
        if zone_to_price:
            snapshots[label] = pd.DataFrame(
                [{"zone": z, "price": p} for z, p in zone_to_price.items()]
            )

    return snapshots
