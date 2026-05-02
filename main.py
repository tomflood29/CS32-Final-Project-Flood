from fetch_data import load_prices
from map_viz2 import build_map

prices = load_prices()
build_map(prices)
