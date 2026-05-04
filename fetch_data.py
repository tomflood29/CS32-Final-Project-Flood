import os
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

# Prefer env vars (recommended). Fallback to your hardcoded values if not set.
ISONE_USER = os.getenv("ISONE_USER", "tomflood@college.harvard.edu")
ISONE_PASS = os.getenv("ISONE_PASS", "CS32Passkey")

BASE = "https://webservices.iso-ne.com/api/v1.1"

_session = requests.Session()

# Cache live prices (5 min) and LocId mapping (1 hour)
_live_cache = {"data": None, "ts": 0}
_locid_cache = {"data": None, "ts": 0}


def _get(url: str, timeout=(5, 45)) -> requests.Response:
    """Small wrapper so all requests behave the same way."""
    return _session.get(
        url,
        headers={"Accept": "application/json"},
        auth=(ISONE_USER, ISONE_PASS),
        timeout=timeout,
    )


def fetch_zone_locids(force_refresh=False) -> dict:
    """
    Returns mapping: zone_code (e.g. '.Z.MAINE') -> numeric LocId string (e.g. '12345').

    We discover LocIds by calling the current 5-minute LMP feed and reading:
      entry["Location"]["$"]      -> '.Z.MAINE'
      entry["Location"]["@LocId"] -> numeric id required by /hourlylmp/.../location/{locationId}
    """
    if (not force_refresh) and (time.time() - _locid_cache["ts"] < 3600) and _locid_cache["data"]:
        return _locid_cache["data"]

    url = f"{BASE}/fiveminutelmp/current/all.json"
    r = _get(url, timeout=(5, 45))
    r.raise_for_status()
    data = r.json()

    root = data.get("FiveMinLmps") or data.get("FiveMinLmp")
    if not root:
        raise RuntimeError(f"Unexpected JSON structure for fiveminutelmp. Top keys: {list(data.keys())}")

    lmps = root.get("FiveMinLmp", [])
    if isinstance(lmps, dict):
        lmps = [lmps]

    zone_to_locid = {}
    for entry in lmps:
        loc = entry.get("Location", {})
        zone_code = loc.get("$")          # '.Z.MAINE'
        locid = loc.get("@LocId")         # numeric id

        if zone_code in ISONE_ZONES and locid is not None:
            zone_to_locid[zone_code] = str(locid)

    if not zone_to_locid:
        raise RuntimeError("Could not discover any LocIds for zones. Check ISO-NE response / credentials.")

    _locid_cache["data"] = zone_to_locid
    _locid_cache["ts"] = time.time()
    return zone_to_locid


def fetch_live_prices():
    """Fetch latest 5-minute LMPs for your zones."""
    if time.time() - _live_cache["ts"] < 300 and _live_cache["data"] is not None:
        return _live_cache["data"]

    url = f"{BASE}/fiveminutelmp/current/all.json"
    r = _get(url, timeout=(5, 45))
    r.raise_for_status()

    data = r.json()
    # Keep your debug dump if you want
    with open("api_response.json", "w") as f:
        json.dump(data, f, indent=2)
    print("Response saved to api_response.json")

    root = data.get("FiveMinLmps") or data.get("FiveMinLmp")
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

    df = pd.DataFrame(rows)
    _live_cache["data"] = df
    _live_cache["ts"] = time.time()
    return df


def fetch_historical_prices(hours_back=24):
    """
    Fetch hourly RT preliminary LMPs for the last N *completed* hours.

    Returns:
      snapshots: dict { "YYYY-MM-DD HH:00": DataFrame(zone, price) }
    """
    tz = ZoneInfo("America/New_York")

    # Use the last completed hour window: [end-hours_back, ..., end-1]
    end_hour = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour - timedelta(hours=hours_back)
    wanted_hours = [start_hour + timedelta(hours=i) for i in range(hours_back)]
    wanted_labels = {dt.strftime("%Y-%m-%d %H:00") for dt in wanted_hours}

    needed_days = sorted({dt.strftime("%Y%m%d") for dt in wanted_hours})

    # Prepare structure label -> dict(zone_name -> price)
    prices_by_label = {dt.strftime("%Y-%m-%d %H:00"): {} for dt in wanted_hours}

    zone_locids = fetch_zone_locids()

    for zone_code, zone_name in ISONE_ZONES.items():
        locid = zone_locids.get(zone_code)
        if not locid:
            print(f"Missing LocId for {zone_code}; skipping")
            continue

        for day_str in needed_days:
            url = f"{BASE}/hourlylmp/rt/prelim/day/{day_str}/location/{locid}.json"

            try:
                r = _get(url, timeout=(5, 60))
            except requests.exceptions.ReadTimeout:
                print("Hourly timed out:", url)
                continue
            except requests.exceptions.RequestException as e:
                print("Hourly request error:", e, url)
                continue

            if r.status_code != 200:
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
