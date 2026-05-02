import folium
import geopandas as gpd
from shapely.geometry import box

def make_zone_shapes():
    zones = [
        {"zone": "Maine",                          "geometry": box(-71.1, 43.0, -67.0, 47.5)}, # maps the latitude and longtitude locations on the map of the zones
        {"zone": "New Hampshire",                  "geometry": box(-72.6, 42.7, -70.7, 45.3)},
        {"zone": "Vermont",                        "geometry": box(-73.4, 42.7, -71.5, 45.0)},
        {"zone": "Connecticut",                    "geometry": box(-73.7, 40.9, -71.8, 42.1)},
        {"zone": "Rhode Island",                   "geometry": box(-71.9, 41.1, -71.1, 42.0)},
        {"zone": "Southeast Massachusetts",        "geometry": box(-71.1, 41.5, -69.9, 42.2)},
        {"zone": "West/Central Massachusetts",     "geometry": box(-73.5, 41.9, -71.5, 42.9)},
        {"zone": "Northeast Massachusetts/Boston", "geometry": box(-71.5, 42.1, -70.5, 42.9)},
    ]
    return gpd.GeoDataFrame(zones, crs="EPSG:4326") #crs confirms that it is long / lat

def build_map(prices_df):
    gdf = make_zone_shapes()
    gdf = gdf.merge(prices_df, on="zone") #matches price to zone

    m = folium.Map(location=[43.5, -71.5], zoom_start=7) # this opens the map on New England

    folium.Choropleth(
        geo_data=gdf.to_json(), #tells to convert gdf to something folium can understand
        data=gdf, # what data to use
        columns=["zone", "price"], #which columns from the data
        key_on="feature.properties.zone",
        fill_color="RdYlGn_r", #scale for expensive = red, cheap = green
        legend_name="Electricity Price ($/MWh)",
    ).add_to(m) #adds to map

    folium.GeoJson(
        gdf.to_json(),
        tooltip=folium.GeoJsonTooltip(fields=["zone", "price"]), # allows user to hover over a zone and price data comes up
    ).add_to(m)

    m.save("map.html")
    print("Map saved to map.html")
