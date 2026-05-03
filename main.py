from fetch_data2 import fetch_live_prices, fetch_historical_prices
from map_viz2 import build_map

prices = fetch_live_prices()
snapshots  = fetch_historical_prices(hours_back=24)
build_map(prices, snapshots=snapshots)
