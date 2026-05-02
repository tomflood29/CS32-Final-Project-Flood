import requests
import pandas as pd

#assign numeric ID to Names 
ISONE_ZONE_IDS = {
    ".Z.MAINE":          "Maine",
    ".Z.NEWHAMPSHIRE":   "New Hampshire",
    ".Z.VERMONT":        "Vermont",
    ".Z.CONNECTICUT":    "Connecticut",
    ".Z.RHODEISLAND":    "Rhode Island",
    ".Z.SEMASS":         "Southeast Massachusetts",
    ".Z.WCMASS":         "West/Central Massachusetts",
    ".Z.NEMASSBOST":     "Northeast Massachusetts/Boston",
}



def fetch_live_prices():
    url = "https://webservices.iso-ne.com/api/v1.1/realtimelbmp/current"

    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()  # raises an error if the request failed

    data = response.json()

    # The response nests data under these keys
    lmps = data["RtLbmp"]["RtLbmps"]["RtLbmp"]

    rows = []
    for entry in lmps:
        location_id = entry["Location"]["@LocId"]  # e.g. ".Z.MAINE"
        if location_id in ISONE_ZONE_IDS:
            rows.append({
                "zone":  ISONE_ZONE_IDS[location_id],
                "price": float(entry["LmpTotal"]),
            })

    return pd.DataFrame(rows)
