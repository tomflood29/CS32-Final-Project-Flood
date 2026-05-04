from fetch_data3 import fetch_live_prices, fetch_historical_prices
from map_viz3 import build_map

prices = fetch_live_prices()
snapshots  = fetch_historical_prices(hours_back=24)
print("historical frames:", len(snapshots))
print("historical labels:", list(snapshots.keys())[:5], "...")
build_map(prices, snapshots=snapshots)
