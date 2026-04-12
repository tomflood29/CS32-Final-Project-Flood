"""
map_viz.py
----------
Builds an interactive choropleth map of ISO New England load zones,
coloured by LMP electricity price and with hover tooltips.

Requires:
    pip install folium geopandas requests pandas

How it works:
    1. Loads ISO-NE zone boundaries from a public GeoJSON source.
    2. Merges the zone boundary shapes with the LMP price DataFrame
       produced by fetch_data.py.
    3. Renders a Folium choropleth map where:
         - Fill colour  → total LMP price (green = cheap, red = expensive)
         - Tooltip      → zone name, LMP, congestion, energy, loss
         - Marker icons → flag zones with high congestion as "pressure points"
    4. Saves the result as an HTML file you can open in any browser.
"""

import json
import os
import webbrowser

import folium
import geopandas as gpd
import pandas as pd
import requests
from folium.features import GeoJsonTooltip


# ---------------------------------------------------------------------------
# ISO-NE zone GeoJSON
# ---------------------------------------------------------------------------
# ISO New England publishes zone shapefiles, but for ease of use we reference
# a GeoJSON that maps the 8 load zone names to polygon geometries.
# This URL points to a community-maintained file on GitHub that mirrors the
# official ISO-NE shapefiles in GeoJSON format.
# If this URL changes, replace it with any GeoJSON whose "zone" property
# matches the keys in ZONE_NAME_TO_KEY below.

GEOJSON_URL = (
    "https://raw.githubusercontent.com/openisone/isone-zones/main/isone_zones.geojson"
)

# Fallback: path to a local file if the remote fetch fails.
# Download from ISO-NE website and put it next to this script if needed.
LOCAL_GEOJSON = "isone_zones.geojson"

# Maps the GeoJSON "zone" property → ISO-NE zone key used in fetch_data.py
# (Adjust if your GeoJSON uses different property names.)
ZONE_NAME_TO_KEY = {
    "Maine":                          ".Z.MAINE",
    "New Hampshire":                  ".Z.NEWHAMPSHIRE",
    "Vermont":                        ".Z.VERMONT",
    "Connecticut":                    ".Z.CONNECTICUT",
    "Rhode Island":                   ".Z.RHODEISLAND",
    "Southeast Massachusetts":        ".Z.SEMASS",
    "West/Central Massachusetts":     ".Z.WCMASS",
    "Northeast Massachusetts/Boston": ".Z.NEMASSBOST",
}

# Congestion threshold ($/MWh) above which a zone is flagged as a pressure point
CONGESTION_THRESHOLD = 8.0

# Output HTML file
OUTPUT_FILE = "isone_map.html"


# ---------------------------------------------------------------------------
# load_zone_geodataframe()
# ---------------------------------------------------------------------------
def load_zone_geodataframe() -> gpd.GeoDataFrame:
    """
    Load ISO-NE zone boundaries as a GeoDataFrame.

    Tries the remote GeoJSON first; falls back to a local file.
    If neither is available, returns a minimal synthetic GeoDataFrame
    so the rest of the pipeline can still be tested.
    """
    # Try remote
    try:
        resp = requests.get(GEOJSON_URL, timeout=10)
        resp.raise_for_status()
        gdf = gpd.GeoDataFrame.from_features(
            resp.json()["features"], crs="EPSG:4326"
        )
        print(f"[map_viz] Loaded zone GeoJSON from remote ({len(gdf)} features).")
        return gdf
    except Exception as e:
        print(f"[map_viz] Remote GeoJSON fetch failed: {e}")

    # Try local file
    if os.path.exists(LOCAL_GEOJSON):
        gdf = gpd.read_file(LOCAL_GEOJSON)
        print(f"[map_viz] Loaded zone GeoJSON from local file ({len(gdf)} features).")
        return gdf

    # Last resort: bounding-box rectangles that roughly cover each zone.
    # These are NOT accurate — replace with real shapes as soon as possible.
    print("[map_viz] WARNING: Using synthetic placeholder geometries.")
    from shapely.geometry import box
    placeholder = [
        {"zone_name": "Maine",                          "geometry": box(-71.1, 43.0, -67.0, 47.5)},
        {"zone_name": "New Hampshire",                  "geometry": box(-72.6, 42.7, -70.7, 45.3)},
        {"zone_name": "Vermont",                        "geometry": box(-73.4, 42.7, -71.5, 45.0)},
        {"zone_name": "Connecticut",                    "geometry": box(-73.7, 40.9, -71.8, 42.1)},
        {"zone_name": "Rhode Island",                   "geometry": box(-71.9, 41.1, -71.1, 42.0)},
        {"zone_name": "Southeast Massachusetts",        "geometry": box(-71.1, 41.5, -69.9, 42.2)},
        {"zone_name": "West/Central Massachusetts",     "geometry": box(-73.5, 41.9, -71.5, 42.9)},
        {"zone_name": "Northeast Massachusetts/Boston", "geometry": box(-71.5, 42.1, -70.5, 42.9)},
    ]
    return gpd.GeoDataFrame(placeholder, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# merge_prices_with_geodata()
# ---------------------------------------------------------------------------
def merge_prices_with_geodata(
    gdf: gpd.GeoDataFrame,
    lmp_df: pd.DataFrame,
    zone_col: str = "zone_name",
) -> gpd.GeoDataFrame:
    """
    Join LMP price data onto the GeoDataFrame.

    Parameters
    ----------
    gdf       : GeoDataFrame with zone boundaries (must have a zone name column)
    lmp_df    : DataFrame from fetch_data.py (must have zone_name column)
    zone_col  : The column in gdf that holds zone names

    Returns a GeoDataFrame with price columns attached to each zone polygon.
    """
    # Normalise zone names for matching
    gdf = gdf.copy()
    gdf["_zone_key"] = gdf[zone_col].map(ZONE_NAME_TO_KEY)

    merged = gdf.merge(
        lmp_df[["zone_key", "lmp", "energy", "congestion", "loss"]],
        left_on="_zone_key",
        right_on="zone_key",
        how="left",
    )

    missing = merged["lmp"].isna().sum()
    if missing > 0:
        print(f"[map_viz] Warning: {missing} zone(s) could not be matched to price data.")
        merged["lmp"] = merged["lmp"].fillna(0)
        merged["congestion"] = merged["congestion"].fillna(0)
        merged["energy"] = merged["energy"].fillna(0)
        merged["loss"] = merged["loss"].fillna(0)

    # Flag pressure points
    merged["pressure_point"] = merged["congestion"] >= CONGESTION_THRESHOLD

    print(f"[map_viz] Merged {len(merged)} zones. "
          f"{merged['pressure_point'].sum()} pressure point(s) detected.")
    return merged


# ---------------------------------------------------------------------------
# build_map()
# ---------------------------------------------------------------------------
def build_map(merged_gdf: gpd.GeoDataFrame) -> folium.Map:
    """
    Build the Folium interactive map.

    - Choropleth layer coloured by total LMP
    - GeoJson layer for rich hover tooltips
    - Circle markers on pressure-point zones
    """
    # Centre the map on New England
    m = folium.Map(
        location=[43.5, -71.5],
        zoom_start=7,
        tiles="CartoDB positron",
    )

    # Convert to GeoJSON string for Folium
    geojson_str = merged_gdf.to_json()

    # --- Choropleth: fills each zone by LMP price ---
    folium.Choropleth(
        geo_data=geojson_str,
        data=merged_gdf,
        columns=["zone_name", "lmp"],    # match column used as key
        key_on="feature.properties.zone_name",
        fill_color="RdYlGn_r",           # Red = expensive, Green = cheap
        fill_opacity=0.65,
        line_opacity=0.8,
        legend_name="Real-Time LMP ($/MWh)",
        nan_fill_color="lightgrey",
        highlight=True,
    ).add_to(m)

    # --- Tooltip layer: hover to see full price breakdown ---
    tooltip = GeoJsonTooltip(
        fields=["zone_name", "lmp", "energy", "congestion", "loss"],
        aliases=["Zone", "LMP ($/MWh)", "Energy ($/MWh)", "Congestion ($/MWh)", "Loss ($/MWh)"],
        localize=True,
        sticky=True,
        labels=True,
        style=(
            "background-color: #1a1a2e; color: #eee; "
            "font-family: monospace; font-size: 13px; "
            "padding: 8px; border-radius: 4px;"
        ),
    )

    folium.GeoJson(
        geojson_str,
        style_function=lambda feature: {
            "fillColor": "transparent",
            "color": "#333",
            "weight": 1.5,
            "fillOpacity": 0,
        },
        highlight_function=lambda feature: {
            "weight": 3,
            "color": "#ffffff",
            "fillOpacity": 0.1,
        },
        tooltip=tooltip,
    ).add_to(m)

    # --- Pressure point markers ---
    for _, row in merged_gdf[merged_gdf["pressure_point"]].iterrows():
        centroid = row.geometry.centroid
        folium.CircleMarker(
            location=[centroid.y, centroid.x],
            radius=14,
            color="#ff4444",
            fill=True,
            fill_color="#ff4444",
            fill_opacity=0.35,
            popup=folium.Popup(
                f"<b>⚡ Pressure Point</b><br>"
                f"{row['zone_name']}<br>"
                f"Congestion: <b>${row['congestion']:.2f}/MWh</b><br>"
                f"Total LMP: <b>${row['lmp']:.2f}/MWh</b>",
                max_width=220,
            ),
            tooltip=f"⚡ {row['zone_name']}: High Congestion",
        ).add_to(m)

    # --- Title box ---
    title_html = """
    <div style="
        position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
        z-index: 1000; background: rgba(26,26,46,0.92);
        padding: 10px 22px; border-radius: 8px;
        font-family: monospace; color: #eee; font-size: 15px;
        border: 1px solid #444; box-shadow: 0 2px 10px rgba(0,0,0,0.4);">
        <b>ISO New England — Real-Time Electricity Prices</b><br>
        <span style="font-size:11px; color:#aaa;">
            Hover over a zone · Red markers = grid pressure points
        </span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    return m


# ---------------------------------------------------------------------------
# save_and_open()
# ---------------------------------------------------------------------------
def save_and_open(m: folium.Map, path: str = OUTPUT_FILE, auto_open: bool = True):
    """Save the map to an HTML file and optionally open it in the browser."""
    m.save(path)
    print(f"[map_viz] Map saved to: {os.path.abspath(path)}")
    if auto_open:
        webbrowser.open(f"file://{os.path.abspath(path)}")


# ---------------------------------------------------------------------------
# generate_map() — convenience wrapper called by main.py
# ---------------------------------------------------------------------------
def generate_map(lmp_df: pd.DataFrame, output_path: str = OUTPUT_FILE):
    """
    End-to-end: load geodata, merge prices, build map, save.
    Call this from main.py.
    """
    gdf = load_zone_geodataframe()
    merged = merge_prices_with_geodata(gdf, lmp_df)
    m = build_map(merged)
    save_and_open(m, path=output_path)
    return m


# ---------------------------------------------------------------------------
# Quick test — run this file on its own to preview the map
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from fetch_data import _sample_lmp_dataframe
    sample_df = _sample_lmp_dataframe()
    generate_map(sample_df)
