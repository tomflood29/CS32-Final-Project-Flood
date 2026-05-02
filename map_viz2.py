import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import box

NEW_ENGLAND_STATES = [
    "Maine", "New Hampshire", "Vermont",
    "Connecticut", "Rhode Island", "Massachusetts"
]

def load_state_shapes(shapefile_path):
    """Load real state boundaries from a Census Bureau shapefile."""
    gdf = gpd.read_file(shapefile_path)          # reads all 50 states
    gdf = gdf.to_crs("EPSG:4326") # converts to a 
    gdf = gdf[gdf["NAME"].isin(NEW_ENGLAND_STATES)]  # keep only New England
    gdf = gdf[["NAME", "geometry"]].rename(columns={"NAME": "state"})
    return gdf.reset_index(drop=True)


def split_massachusetts(gdf):
    """Split the single MA polygon into three ISO-NE zones."""
    ma_geom = gdf.loc[gdf["state"] == "Massachusetts", "geometry"].values[0]

    # Define rough clipping boxes for each zone
    west_clip  = box(-73.5, 41.9, -71.5, 42.9)   # west of ~71.5°W
    ne_clip    = box(-71.5, 42.15, -70.5, 42.9)   # northeast quadrant
    se_clip    = box(-71.5, 41.5, -69.9, 42.15)   # southeast / Cape Cod

    mass_zones = gpd.GeoDataFrame([
        {"zone": "West/Central Massachusetts",     "geometry": ma_geom.intersection(west_clip)},
        {"zone": "Northeast Massachusetts/Boston", "geometry": ma_geom.intersection(ne_clip)},
        {"zone": "Southeast Massachusetts",        "geometry": ma_geom.intersection(se_clip)},
    ], crs="EPSG:4326")

    return mass_zones


def make_zone_shapes(shapefile_path):
    gdf = load_state_shapes(shapefile_path)

    # Drop Massachusetts — we'll replace it with the three sub-zones
    other_states = gdf[gdf["state"] != "Massachusetts"].copy()
    other_states = other_states.rename(columns={"state": "zone"})

    mass_zones = split_massachusetts(gdf)

    all_zones = pd.concat([other_states, mass_zones], ignore_index=True)
    return gpd.GeoDataFrame(all_zones, crs="EPSG:4326")


def build_map(prices_df, shapefile_path="data/shapefiles/cb_2022_us_state_20m.shp"):
    gdf = make_zone_shapes(shapefile_path)
    gdf = gdf.merge(prices_df, on="zone")

    m = folium.Map(location=[43.5, -71.5], zoom_start=7)

    folium.Choropleth(
        geo_data=gdf.to_json(),
        data=gdf,
        columns=["zone", "price"],
        key_on="feature.properties.zone",
        fill_color="RdYlGn_r",
        fill_opacity=0.7,
        line_opacity=0.8,
        legend_name="Electricity Price ($/MWh)",
    ).add_to(m)

    folium.GeoJson(
        gdf.to_json(),
        tooltip=folium.GeoJsonTooltip(fields=["zone", "price"]),
    ).add_to(m)

    m.save("map.html")
