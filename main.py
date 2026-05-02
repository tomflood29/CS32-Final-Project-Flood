from fetch_data2 import fetch_live_prices
from map_viz2 import build_map

prices = fetch_live_prices()
build_map(prices)
