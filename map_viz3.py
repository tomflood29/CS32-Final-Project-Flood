import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
import json
from branca.element import Element

NEW_ENGLAND_STATES = ["Maine", "New Hampshire", "Vermont", "Connecticut", "Rhode Island", "Massachusetts"]

def load_state_shapes(shapefile_path):
    gdf = gpd.read_file(shapefile_path)
    gdf = gdf.to_crs("EPSG:4326")
    gdf = gdf[gdf["NAME"].isin(NEW_ENGLAND_STATES)]
    return gdf[["NAME", "geometry"]].rename(columns={"NAME": "state"}).reset_index(drop=True)

def split_massachusetts(gdf):
    ma_geom = gdf.loc[gdf["state"] == "Massachusetts", "geometry"].values[0]
    west_clip = box(-73.5, 41.2, -71.8, 42.9)
    ne_clip   = box(-71.8, 42.25, -69.9, 42.9)
    se_clip   = box(-71.8, 41.2, -69.9, 42.25)
    return gpd.GeoDataFrame([
        {"zone": "West/Central Massachusetts",     "geometry": ma_geom.intersection(west_clip)},
        {"zone": "Northeast Massachusetts/Boston", "geometry": ma_geom.intersection(ne_clip)},
        {"zone": "Southeast Massachusetts",        "geometry": ma_geom.intersection(se_clip)},
    ], crs="EPSG:4326")

def make_zone_shapes(shapefile_path):
    gdf = load_state_shapes(shapefile_path)
    others = gdf[gdf["state"] != "Massachusetts"].copy().rename(columns={"state": "zone"})
    mass = split_massachusetts(gdf)
    return gpd.GeoDataFrame(pd.concat([others, mass], ignore_index=True), crs="EPSG:4326")

def build_map(prices_df, snapshots=None, shapefile_path="data/shapefiles/cb_2022_us_state_20m.shp"):
    gdf = make_zone_shapes(shapefile_path)
    m = folium.Map(location=[44.0, -71.5], zoom_start=7, tiles="cartodbpositron")

    # 1. TEMPORAL NORMALIZATION: Find global min/max across all 24 hours
    all_history = {}
    price_pool = prices_df["price"].tolist()

    sorted_labels = sorted(snapshots.keys()) if snapshots else []
    for label in sorted_labels:
        df = snapshots[label]
        all_history[label] = dict(zip(df["zone"], df["price"]))
        price_pool.extend(df["price"].tolist())

    live_label = "LIVE NOW"
    all_history[live_label] = dict(zip(prices_df["zone"], prices_df["price"]))
    full_sequence = sorted_labels + [live_label]


    # --- PER-ZONE NORMALIZATION ---
    # Build zone -> list of prices over time
    zone_series = {z: [] for z in gdf["zone"].tolist()}

    for label, zone_to_price in all_history.items():
        for z in zone_series.keys():
            p = zone_to_price.get(z)
            if p is not None:
                zone_series[z].append(p)

    # zone -> {"min": ..., "max": ...}
    zone_minmax = {}
    for z, series in zone_series.items():
        if series:
            zone_minmax[z] = {"min": float(min(series)), "max": float(max(series))}
        else:
            zone_minmax[z] = {"min": 0.0, "max": 1.0}  # fallback


    # 2. INJECT ANIMATION INTERFACE
    animation_html = f"""
    <div id="anim-panel" style="position: fixed; bottom: 30px; left: 30px; width: 330px;
         z-index:9999; background: white; padding: 20px; border-radius: 12px;
         box-shadow: 0 8px 24px rgba(0,0,0,0.2); font-family: sans-serif;">

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <b style="font-size: 14px;">ISO-NE Price Pulse (24h)</b>
            <span id="txt-time" style="font-weight: bold; color: white; background: #2196F3; padding: 2px 8px; border-radius: 4px; font-size: 11px;">LIVE</span>
        </div>

        <input id="slider" type="range" min="0" max="{len(full_sequence)-1}" value="{len(full_sequence)-1}" style="width: 100%;">

        <div style="display: flex; gap: 10px; margin: 15px 0;">
            <button id="play" style="flex: 1; padding: 8px; background: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer;">Play</button>
            <button id="pause" style="flex: 1; padding: 8px; background: #95a5a6; color: white; border: none; border-radius: 4px; cursor: pointer;">Pause</button>
        </div>

        <div style="font-size: 10px; color: #666;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span>Cheap (${{p_min.toFixed(2)}})</span>
                <span>Spike (${{p_max.toFixed(2)}})</span>
            </div>
            <div style="height: 8px; width: 100%; background: linear-gradient(to right, #2ecc71, #f1c40f, #e74c3c); border-radius: 4px;"></div>
        </div>
    </div>

    <script>
    (function() {{
        const snapshots = {json.dumps(all_history)};
        const labels = {json.dumps(full_sequence)};
        const geojson = {gdf[["zone", "geometry"]].to_json()};
        const zoneMinMax = {json.dumps(zone_minmax)};

        let currentLayer = null, animTimer = null, currentIdx = labels.length - 1;

        function getColor(zone, p) {
            if (p == null) return '#ccc';
            const mm = zoneMinMax[zone];
            if (!mm) return '#ccc';
            const denom = (mm.max - mm.min) || 1;
            const t = Math.max(0, Math.min(1, (p - mm.min) / denom));
            let r = t < 0.5 ? Math.floor(255 * (t * 2)) : 255;
            let g = t < 0.5 ? 255 : Math.floor(255 * (1 - (t - 0.5) * 2));
            return `rgb(${r},${g},40)`;
            }
        function render(idx) {{
            const map = window[Object.keys(window).find(k => k.startsWith('map_'))];
            currentIdx = idx;
            const label = labels[idx];
            const prices = snapshots[label];

            document.getElementById('txt-time').innerText = label;
            document.getElementById('slider').value = idx;

            if (currentLayer) map.removeLayer(currentLayer);

            currentLayer = L.geoJson(geojson, {{
                style: (f) => ({{
                    fillColor: getColor(prices[f.properties.zone]),
                    fillOpacity: 0.8, color: 'white', weight: 1.5
                }}),
                onEachFeature: (f, l) => {{
                    const p = prices[f.properties.zone];
                    l.bindTooltip(`<b>${{f.properties.zone}}</b><br>$${{p ? p.toFixed(2) : "N/A"}}/MWh`);
                }}
            }}).addTo(map);
        }}

        document.getElementById('slider').oninput = (e) => {{ clearInterval(animTimer); render(parseInt(e.target.value)); }};
        document.getElementById('play').onclick = () => {{
            clearInterval(animTimer);
            animTimer = setInterval(() => {{
                currentIdx = (currentIdx + 1) % labels.length;
                render(currentIdx);
            }}, 600);
        }};
        document.getElementById('pause').onclick = () => clearInterval(animTimer);

        setTimeout(() => render(labels.length - 1), 500);
    }})();
    </script>
    """
    m.get_root().html.add_child(Element(animation_html))
    m.save("map.html")
    print("Map saved to map.html")
