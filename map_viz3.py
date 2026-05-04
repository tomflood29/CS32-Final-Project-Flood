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

    # IMPORTANT: left-join so you never "lose" polygons if a zone name is missing in prices_df
    gdf = gdf.merge(prices_df, on="zone", how="left")

    m = folium.Map(location=[43.5, -71.5], zoom_start=7)

    # Base choropleth (live). This is just a backdrop; we’ll overlay our own colored layer for live+historical.
    # Fill NaNs so Choropleth doesn't break if a zone is missing.
    gdf_for_choro = gdf.copy()
    gdf_for_choro["price"] = gdf_for_choro["price"].fillna(0.0)

    folium.Choropleth(
        geo_data=gdf_for_choro.to_json(),
        data=gdf_for_choro,
        columns=["zone", "price"],
        key_on="feature.properties.zone",
        fill_color="RdYlGn_r",
        fill_opacity=0.35,
        line_opacity=0.8,
        legend_name="Electricity Price ($/MWh) (base layer)",
    ).add_to(m)

    # Tooltips for the base layer
    folium.GeoJson(
        gdf_for_choro.to_json(),
        tooltip=folium.GeoJsonTooltip(fields=["zone", "price"]),
    ).add_to(m)

    if snapshots:
        geojson_str = gdf[["zone", "geometry"]].to_json()

        # --- Build historical data dict: { label: { zone: price } } ---
        all_data = {}
        for label, df in snapshots.items():
            all_data[label] = dict(zip(df["zone"], df["price"]))

        # Sort labels so the slider moves chronologically
        time_labels = sorted(all_data.keys())

        # Live prices dict for JS "live overlay"
        live_data = dict(zip(prices_df["zone"], prices_df["price"]))

        # --- PER-ZONE MIN/MAX over the whole window (historical + live) ---
        zones = gdf["zone"].tolist()
        zone_minmax = {}
        for z in zones:
            series = []

            # historical
            for lab in time_labels:
                p = all_data.get(lab, {}).get(z)
                if p is not None:
                    series.append(float(p))

            # live
            p_live = live_data.get(z)
            if p_live is not None:
                series.append(float(p_live))

            if series:
                zone_minmax[z] = {"min": float(min(series)), "max": float(max(series))}
            else:
                # no data: JS will render grey
                zone_minmax[z] = {"min": None, "max": None}

        slider_js = f"""
        <div id="slider-container" style="
            position: fixed;
            top: 20px;
            left: 20px;
            z-index: 9999;
            background: white;
            padding: 14px 18px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            font-family: Arial, sans-serif;
            min-width: 320px;
        ">
            <div style="font-weight: bold; font-size: 14px; margin-bottom: 6px;">
                Historical Prices (Last 24 Hours)
            </div>
            <div id="time-display" style="
                font-size: 18px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 8px;
            ">Live ▶</div>
            <input
                type="range"
                id="time-slider"
                min="-1"
                max="{len(time_labels) - 1}"
                value="-1"
                step="1"
                style="width: 100%;"
            >
            <div style="display: flex; justify-content: space-between; font-size: 11px; color: #888; margin-top: 4px;">
                <span>24h ago</span>
                <span>← Drag →</span>
                <span>Live</span>
            </div>

            <div style="font-size: 10px; color: #666; margin-top: 10px; line-height: 1.2;">
                <b>Color scale (per zone):</b><br>
                Green = low for that zone (24h), Red = high for that zone (24h)
            </div>
        </div>

        <script>
            const allData      = {json.dumps(all_data)};
            const timeLabels   = {json.dumps(time_labels)};
            const geojsonData  = {geojson_str};

            // NEW:
            const liveData     = {json.dumps(live_data)};
            const zoneMinMax   = {json.dumps(zone_minmax)};

            document.addEventListener("DOMContentLoaded", function() {{

                function getMap() {{
                    // Find the Leaflet map instance folium created
                    for (let key in window) {{
                        if (window[key] && window[key]._leaflet_id !== undefined && window[key].getCenter) {{
                            return window[key];
                        }}
                    }}
                    return null;
                }}

                // Per-zone color: uses zoneMinMax[zone].min/max
                function getColor(zone, price) {{
                    if (price === undefined || price === null) return '#cccccc';

                    const mm = zoneMinMax[zone];
                    if (!mm || mm.min === null || mm.max === null) return '#cccccc';

                    const minP = mm.min;
                    const maxP = mm.max;

                    let t;
                    if (maxP === minP) {{
                        // flat series: use middle color
                        t = 0.5;
                    }} else {{
                        t = Math.max(0, Math.min(1, (price - minP) / (maxP - minP)));
                    }}

                    // Green (low) → Yellow → Red (high)
                    let r, g;
                    if (t < 0.5) {{
                        r = Math.round(255 * (t * 2));
                        g = 255;
                    }} else {{
                        r = 255;
                        g = Math.round(255 * (1 - (t - 0.5) * 2));
                    }}
                    return `rgb(${{r}}, ${{g}}, 0)`;
                }}

                let overlayLayer = null;

                function drawOverlay(pricesByZone, labelText) {{
                    const leafletMap = getMap();
                    if (!leafletMap) return;

                    document.getElementById('time-display').textContent = labelText;

                    if (overlayLayer) {{
                        leafletMap.removeLayer(overlayLayer);
                    }}

                    overlayLayer = L.geoJSON(geojsonData, {{
                        style: function(feature) {{
                            const zone = feature.properties.zone;
                            const price = pricesByZone[zone];
                            return {{
                                fillColor:   getColor(zone, price),
                                fillOpacity: 0.75,
                                color:       'white',
                                weight:      1.5
                            }};
                        }},
                        onEachFeature: function(feature, layer) {{
                            const zone  = feature.properties.zone;
                            const price = pricesByZone[zone];

                            const mm = zoneMinMax[zone];
                            const rangeText = (mm && mm.min !== null && mm.max !== null)
                                ? `$${{mm.min.toFixed(2)}} – $${{mm.max.toFixed(2)}}`
                                : "N/A";

                            layer.bindTooltip(
                                `<b>${{zone}}</b><br>` +
                                (price !== undefined && price !== null
                                    ? `Now: $${{Number(price).toFixed(2)}}/MWh<br>24h range: ${{rangeText}}`
                                    : `No data<br>24h range: ${{rangeText}}`),
                                {{sticky: true}}
                            );
                        }}
                    }}).addTo(leafletMap);
                }}

                function showHistorical(index) {{
                    const label  = timeLabels[index];
                    const prices = allData[label];
                    drawOverlay(prices, label);
                }}

                function showLive() {{
                    // NEW: live also uses per-zone coloring by drawing an overlay
                    drawOverlay(liveData, 'Live ▶');
                }}

                document.getElementById('time-slider').addEventListener('input', function() {{
                    const val = parseInt(this.value);
                    if (val === -1) {{
                        showLive();
                    }} else {{
                        showHistorical(val);
                    }}
                }});

                // Start in live mode with the per-zone overlay applied
                showLive();
            }});
        </script>
        """

    m.save("map.html")

    if snapshots:
        with open("map.html", "r") as f:
            html = f.read()
        html = html.replace("</body>", slider_js + "</body>")
        with open("map.html", "w") as f:
            f.write(html)

    print("Map saved to map.html")
