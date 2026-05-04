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
    map_var = m.get_name()

    # ----------------------------
    # 1) Build history: label -> {zone_name: price}
    # ----------------------------
    all_history = {}

    # historical frames (sorted so the slider moves forward in time)
    sorted_labels = sorted(snapshots.keys()) if snapshots else []
    for label in sorted_labels:
        df = snapshots[label]
        all_history[label] = dict(zip(df["zone"], df["price"]))

    # live frame at the end
    live_label = "LIVE NOW"
    if prices_df is not None and not prices_df.empty:
        all_history[live_label] = dict(zip(prices_df["zone"], prices_df["price"]))
    else:
        all_history[live_label] = {}

    full_sequence = sorted_labels + [live_label]

    # ----------------------------
    # 2) PER-ZONE normalization: zone -> {min, max} across all frames
    # ----------------------------
    zones = gdf["zone"].tolist()
    zone_minmax = {}

    for z in zones:
        series = []
        for _, zone_to_price in all_history.items():
            p = zone_to_price.get(z)
            if p is not None:
                series.append(float(p))

        if series:
            zone_minmax[z] = {"min": float(min(series)), "max": float(max(series))}
        else:
            zone_minmax[z] = {"min": 0.0, "max": 1.0}

    # ----------------------------
    # 3) UI panel (legend text updated for per-zone scaling)
    # ----------------------------
    panel_html = f"""
    <div id="anim-panel" style="position: fixed; bottom: 30px; left: 30px; width: 340px;
         z-index:9999; background: white; padding: 20px; border-radius: 12px;
         box-shadow: 0 8px 24px rgba(0,0,0,0.2); font-family: sans-serif;">

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <b style="font-size: 14px;">ISO-NE Price Pulse (24h)</b>
            <span id="txt-time" style="font-weight: bold; color: white; background: #2196F3; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{live_label}</span>
        </div>

        <input id="slider" type="range" min="0" max="{len(full_sequence)-1}" value="{len(full_sequence)-1}" style="width: 100%;">

        <div style="display: flex; gap: 10px; margin: 15px 0;">
            <button id="play" type="button" style="flex: 1; padding: 8px; background: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer;">Play</button>
            <button id="pause" type="button" style="flex: 1; padding: 8px; background: #95a5a6; color: white; border: none; border-radius: 4px; cursor: pointer;">Pause</button>
        </div>

        <div style="font-size: 10px; color: #666; line-height: 1.25;">
            <div style="margin-bottom: 6px;">
                <b>Color meaning (per zone):</b><br>
                Green = low for that zone (last 24h), Red = high for that zone (last 24h)
            </div>
            <div style="height: 8px; width: 100%;
                        background: linear-gradient(to right, #2ecc71, #f1c40f, #e74c3c);
                        border-radius: 4px;"></div>
        </div>
    </div>
    """
    m.get_root().html.add_child(Element(panel_html))

    # ----------------------------
    # 4) JS animation + per-zone color scaling
    # ----------------------------
    js = f"""
    <script>
    window.addEventListener('load', function() {{
        const map = {map_var};

        const snapshots = {json.dumps(all_history)};
        const labels = {json.dumps(full_sequence)};
        const geojson = {gdf[["zone", "geometry"]].to_json()};

        // zone -> {{min, max}} computed in Python across the whole 24h window
        const zoneMinMax = {json.dumps(zone_minmax)};

        const panel = document.getElementById('anim-panel');
        if (window.L && panel) {{
            L.DomEvent.disableClickPropagation(panel);
            L.DomEvent.disableScrollPropagation(panel);
        }}

        let currentLayer = null;
        let animTimer = null;
        let currentIdx = labels.length - 1;

        function clamp01(x) {{
            return Math.max(0, Math.min(1, x));
        }}

        function getColor(zone, p) {{
            if (p == null) return '#ccc';

            const mm = zoneMinMax[zone];
            if (!mm) return '#ccc';

            const minP = mm.min;
            const maxP = mm.max;

            // If this zone had a flat line (min == max), use a neutral-ish color
            let t;
            if (maxP === minP) {{
                t = 0.5;
            }} else {{
                t = clamp01((p - minP) / (maxP - minP));
            }}

            // green -> yellow -> red
            let r = (t < 0.5) ? Math.floor(255 * (t * 2)) : 255;
            let g = (t < 0.5) ? 255 : Math.floor(255 * (1 - (t - 0.5) * 2));
            return `rgb(${{r}},${{g}},40)`;
        }}

        function render(idx) {{
            currentIdx = idx;
            const label = labels[idx];
            const prices = snapshots[label] || {{}};

            document.getElementById('txt-time').innerText = label;
            document.getElementById('slider').value = idx;

            if (currentLayer) map.removeLayer(currentLayer);

            currentLayer = L.geoJson(geojson, {{
                style: (f) => {{
                    const zone = f.properties.zone;
                    const p = prices[zone];
                    return {{
                        fillColor: getColor(zone, p),
                        fillOpacity: 0.82,
                        color: 'white',
                        weight: 1.5
                    }};
                }},
                onEachFeature: (f, l) => {{
                    const zone = f.properties.zone;
                    const p = prices[zone];

                    const mm = zoneMinMax[zone] || {{min: null, max: null}};
                    const pTxt = (p == null) ? "N/A" : p.toFixed(2);
                    const rangeTxt =
                        (mm.min == null || mm.max == null)
                            ? "N/A"
                            : `${{mm.min.toFixed(2)}} – ${{mm.max.toFixed(2)}}`;

                    l.bindTooltip(
                        `<b>${{zone}}</b><br>` +
                        `Now: $$${{pTxt}}/MWh<br>` +
                        `24h range (this zone): $$${{rangeTxt}}/MWh`
                    );
                }}
            }}).addTo(map);
        }}

        document.getElementById('slider').addEventListener('input', (e) => {{
            if (animTimer) clearInterval(animTimer);
            render(parseInt(e.target.value, 10));
        }});

        document.getElementById('play').addEventListener('click', () => {{
            if (animTimer) clearInterval(animTimer);
            animTimer = setInterval(() => {{
                currentIdx = (currentIdx + 1) % labels.length;
                render(currentIdx);
            }}, 600);
        }});

        document.getElementById('pause').addEventListener('click', () => {{
            if (animTimer) clearInterval(animTimer);
        }});

        render(currentIdx);
    }});
    </script>
    """
    m.get_root().script.add_child(Element(js))

    m.save("map.html")
    print("Map saved to map.html")
