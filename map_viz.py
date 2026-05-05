import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
import json

NEW_ENGLAND_STATES = ["Maine", "New Hampshire", "Vermont", "Connecticut", "Rhode Island", "Massachusetts"]

def load_state_shapes(shapefile_path):
    gdf = gpd.read_file(shapefile_path) #gets the state lines data from Census Bureau
    gdf = gdf.to_crs("EPSG:4326") #converts to consistent long / lat co-ordinates
    gdf = gdf[gdf["NAME"].isin(NEW_ENGLAND_STATES)] #limits geo data frame to only New England states
    return gdf[["NAME", "geometry"]].rename(columns={"NAME": "state"}).reset_index(drop=True) #limits only the name and geometry of state

def split_massachusetts(gdf): # 3 pricing zones
    ma_geom = gdf.loc[gdf["state"] == "Massachusetts", "geometry"].values[0]
    west_clip = box(-73.5, 41.2, -71.8, 42.9) #cuts it into approximate boxes which reflect ISO-NE boundaries.
    ne_clip   = box(-71.8, 42.25, -69.9, 42.9)
    se_clip   = box(-71.8, 41.2, -69.9, 42.25)
    return gpd.GeoDataFrame([
        {"zone": "West/Central Massachusetts",     "geometry": ma_geom.intersection(west_clip)}, #intersection keeps state shape / outline
        {"zone": "Northeast Massachusetts/Boston", "geometry": ma_geom.intersection(ne_clip)},
        {"zone": "Southeast Massachusetts",        "geometry": ma_geom.intersection(se_clip)},
    ], crs="EPSG:4326")

def make_zone_shapes(shapefile_path):
    gdf = load_state_shapes(shapefile_path)
    others = gdf[gdf["state"] != "Massachusetts"].copy().rename(columns={"state": "zone"})
    mass = split_massachusetts(gdf)
    return gpd.GeoDataFrame(pd.concat([others, mass], ignore_index=True), crs="EPSG:4326") #combines the mass and states into one dataframe

def build_map(prices_df, snapshots=None, shapefile_path="data/shapefiles/cb_2022_us_state_20m.shp"): #snapshots = None means can work without historical data
    gdf = make_zone_shapes(shapefile_path)

    gdf = gdf.merge(prices_df, on="zone", how="left") # Matches zone to price, and keeps zone even if no price data

    m = folium.Map(location=[43.5, -71.5], zoom_start=6) #creates a map, zoomed in on New England co-ordinates

    folium.GeoJson(
        gdf[["zone", "geometry"]].to_json(), #creates a zone which price data can be seen when mouse goes over - colour handled by JSON slider
        style_function=lambda: {
            "fillOpacity": 0.0,
            "color": "white",
            "weight": 1.5,
        },
        tooltip=folium.GeoJsonTooltip(fields=["zone"]), #hover feature, shows details of zone - name + price data
        name="Zones",
    ).add_to(m)

    if snapshots: #deals with historical data + slider
        geojson_str = gdf[["zone", "geometry"]].to_json()

        # Historical data dict: { label: { zone: price } }
        all_data = {label: dict(zip(df["zone"], df["price"])) for label, df in snapshots.items()} #creates a dictionary from 2 dfs, zipped together

        time_labels = sorted(all_data.keys())# Sort labels so index increases with time (left = older, right = newer)
        n_hist = len(time_labels)
        live_data = dict(zip(prices_df["zone"], prices_df["price"]))# Live prices (latest 5-minute prices)

        # min/ max data for zones, used for colouring of zones, for every zone finds min / max data poiny
        zones = gdf["zone"].tolist()
        zone_minmax = {}
        for z in zones:
            series = []
            for lab in time_labels:
                p = all_data.get(lab, {}).get(z)
                if p is not None:
                    series.append(float(p))
            p_live = live_data.get(z)
            if p_live is not None:
                series.append(float(p_live))

            if series:
                zone_minmax[z] = {"min": float(min(series)), "max": float(max(series))}
            else:
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
            min-width: 340px;
        ">
            <div style="font-weight: bold; font-size: 14px; margin-bottom: 6px;">
                Electricity Prices (last 24h)
            </div>

            <div id="time-display" style="
                font-size: 16px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 10px;
            ">Live (5-min)</div>

            <input
                type="range"
                id="time-slider"
                min="0"
                max="{n_hist}"
                value="{n_hist}"
                step="1"
                style="width: 100%;"
            >

            <div style="display: flex; justify-content: space-between; font-size: 11px; color: #888; margin-top: 6px;">
                <span>24h ago</span>
                <span>Hourly</span>
                <span>Live (5-min)</span>
            </div>

            <div style="font-size: 10px; color: #666; margin-top: 10px; line-height: 1.2;">
                <b>Color scale (per zone):</b> green = low (24h), red = high (24h)
            </div>
        </div>

        <script>
            const allData      = {json.dumps(all_data)};
            const timeLabels   = {json.dumps(time_labels)};
            const geojsonData  = {geojson_str};

            const liveData     = {json.dumps(live_data)};
            const zoneMinMax   = {json.dumps(zone_minmax)};

            document.addEventListener("DOMContentLoaded", function() {{

                function getMap() {{
                    for (let key in window) {{
                        if (window[key] && window[key]._leaflet_id !== undefined && window[key].getCenter) {{
                            return window[key];
                        }}
                    }}
                    return null;
                }}

                function clamp01(x) {{
                    return Math.max(0, Math.min(1, x));
                }}

                // Per-zone normalization
                function getColor(zone, price) {{
                    if (price === undefined || price === null) return '#cccccc';

                    const mm = zoneMinMax[zone];
                    if (!mm || mm.min === null || mm.max === null) return '#cccccc';

                    const minP = mm.min;
                    const maxP = mm.max;

                    let t;
                    if (maxP === minP) {{
                        t = 0.5;
                    }} else {{
                        t = clamp01((price - minP) / (maxP - minP));
                    }}

                    // Green -> Yellow -> Red
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

                            const priceText = (price !== undefined && price !== null)
                                ? `$${{Number(price).toFixed(2)}}/MWh`
                                : "No data";

                            layer.bindTooltip(
                                `<b>${{zone}}</b><br>` +
                                `Price: ${{priceText}}<br>` +
                                `24h range: ${{rangeText}}`,
                                {{sticky: true}}
                            );
                        }}
                    }}).addTo(leafletMap);
                }}

                function showAtSliderValue(v) {{
                    // v == n_hist means LIVE (rightmost)
                    if (v === {n_hist}) {{
                        drawOverlay(liveData, "Live (5-min)");
                        return;
                    }}

                    // otherwise historical index
                    const label = timeLabels[v];
                    const prices = allData[label];
                    drawOverlay(prices, label);
                }}

                const slider = document.getElementById('time-slider');

                slider.addEventListener('input', function() {{
                    const v = parseInt(this.value, 10);
                    showAtSliderValue(v);
                }});

                // Start at LIVE (rightmost)
                showAtSliderValue({n_hist});
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
