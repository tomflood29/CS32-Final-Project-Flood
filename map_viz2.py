import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
import json
from folium import Element

NEW_ENGLAND_STATES = [
    "Maine", "New Hampshire", "Vermont",
    "Connecticut", "Rhode Island", "Massachusetts"
]

def load_state_shapes(shapefile_path):
    gdf = gpd.read_file(shapefile_path)          # reads all 50 states
    gdf = gdf.to_crs("EPSG:4326") # converts to a coordinate system which is better to use to split MA
    gdf = gdf[gdf["NAME"].isin(NEW_ENGLAND_STATES)]  # keep only New England
    gdf = gdf[["NAME", "geometry"]].rename(columns={"NAME": "state"}) #renames the columns within the file names
    return gdf.reset_index(drop=True)


def split_massachusetts(gdf):
    #Split the single MA polygon into three ISO-NE zones. NEED TO GO OVER UNDERSTANDING THIS
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


def build_map(prices_df, snapshots= None, shapefile_path="data/shapefiles/cb_2022_us_state_20m.shp"):
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

    if snapshots:
        geojson_str = gdf[["zone", "geometry"]].to_json()

        # Build historical data dict: { label: { zone: price } }
        all_data = {}
        all_prices = []  # collect all prices to compute min/max for relative coloring
        for label, df in snapshots.items():
            all_data[label] = dict(zip(df["zone"], df["price"]))
            all_prices.extend(df["price"].tolist())

        # Also include live prices in the range calculation
        all_prices.extend(prices_df["price"].tolist())
        price_min = min(all_prices)
        price_max = max(all_prices)

        time_labels = list(all_data.keys())

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
                🕐 Historical Prices (Last 24 Hours)
            </div>
            <div id="time-display" style="
                font-size: 18px;
                font-weight: bold;
                color: #2196F3;
                margin-bottom: 8px;
            ">Live</div>
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
        </div>

        <script>
            const allData      = {json.dumps(all_data)};
            const timeLabels   = {json.dumps(time_labels)};
            const geojsonData  = {geojson_str};
            const priceMin     = {price_min};
            const priceMax     = {price_max};

            // Wait for the folium map object to be ready
            document.addEventListener("DOMContentLoaded", function() {{

                // Find the Leaflet map instance folium created
                const mapEl = document.querySelector('.folium-map');
                const mapId = mapEl ? mapEl.id : null;

                // Leaflet stores map instances on window keyed by their div id
                function getMap() {{
                    for (let key in window) {{
                        if (window[key] && window[key]._leaflet_id !== undefined
                            && window[key].getCenter) {{
                            return window[key];
                        }}
                    }}
                }}

                // Color based on price relative to 24h min/max
                function getColor(price) {{
                    if (price === undefined || price === null) return '#cccccc';
                    const t = Math.max(0, Math.min(1, (price - priceMin) / (priceMax - priceMin)));
                    // Green (cheap) → Yellow → Red (expensive)
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

                let historicalLayer = null;

                function showHistorical(index) {{
                    const leafletMap = getMap();
                    if (!leafletMap) return;

                    const label  = timeLabels[index];
                    const prices = allData[label];

                    document.getElementById('time-display').textContent = label;

                    if (historicalLayer) {{
                        leafletMap.removeLayer(historicalLayer);
                    }}

                    historicalLayer = L.geoJSON(geojsonData, {{
                        style: function(feature) {{
                            const price = prices[feature.properties.zone];
                            return {{
                                fillColor:   getColor(price),
                                fillOpacity: 0.75,
                                color:       'white',
                                weight:      1.5
                            }};
                        }},
                        onEachFeature: function(feature, layer) {{
                            const zone  = feature.properties.zone;
                            const price = prices[zone];
                            layer.bindTooltip(
                                `<b>${{zone}}</b><br>` +
                                (price !== undefined
                                    ? `$${{price.toFixed(2)}}/MWh`
                                    : 'No data'),
                                {{sticky: true}}
                            );
                        }}
                    }}).addTo(leafletMap);
                }}

                function showLive() {{
                    const leafletMap = getMap();
                    if (!leafletMap) return;

                    document.getElementById('time-display').textContent = 'Live ▶';

                    if (historicalLayer) {{
                        leafletMap.removeLayer(historicalLayer);
                        historicalLayer = null;
                    }}
                    // Live view falls back to the folium choropleth underneath
                }}

                document.getElementById('time-slider').addEventListener('input', function() {{
                    const val = parseInt(this.value);
                    if (val === -1) {{
                        showLive();
                    }} else {{
                        showHistorical(val);
                    }}
                }});
            }});
        </script>
        """

        m.get_root().html.add_child(Element(slider_js))

    m.save("map.html")
    print("Map saved to map.html")
    m.save("map.html")
