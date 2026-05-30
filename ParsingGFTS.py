import zipfile
import pandas as pd
import os
import json
from datetime import datetime
import networkx as nx
import matplotlib.pyplot as plt

filePath = "Examine-Vienna-Subway-Student-Project/gtfs_path.zip"


def time_to_seconds(t):
    """Convert HH:MM:SS to seconds (handles times > 24h in GTFS)."""
    h, m, s = map(int, t.strip().split(':'))
    return h * 3600 + m * 60 + s

def gtfs_to_graph(gtfs_folder, route_types={1}):
    """
    gtfs_folder: path to the folder containing stops.txt, routes.txt, etc.
    """

    def read(name):
        if zipfile.is_zipfile(gtfs_folder):
            with zipfile.ZipFile(gtfs_folder, 'r') as z:
                for zip_path in z.namelist():
                    if zip_path.endswith(name):
                        with z.open(zip_path) as f:
                            return pd.read_csv(f, dtype=str)
                raise FileNotFoundError(f"{name} not found in {gtfs_folder}")

    # Read dataframes
    routes     = read('routes.txt')
    trips      = read('trips.txt')
    stop_times = read('stop_times.txt')
    stops      = read('stops.txt')
    
    # Try reading shapes.txt if it exists in the zip
    has_shapes = False
    try:
        shapes = read('shapes.txt')
        has_shapes = True
    except Exception as e:
        print("Warning: shapes.txt not found or could not be read. Falling back to straight lines.")

    # Convert to correct types
    routes['route_type'] = routes['route_type'].astype(int)
    stop_times['stop_sequence'] = stop_times['stop_sequence'].astype(int)
    stops['stop_lat'] = stops['stop_lat'].astype(float)
    stops['stop_lon'] = stops['stop_lon'].astype(float)

    # Filter to target route types
    subway_routes     = routes[routes['route_type'].isin(route_types)].copy()
    subway_trip       = trips[trips['route_id'].isin(subway_routes['route_id'])].copy()
    subway_stop_times = stop_times[stop_times['trip_id'].isin(subway_trip['trip_id'])].copy()
    subway_stops      = stops[stops['stop_id'].isin(subway_stop_times['stop_id'])].copy()

    # --- 1. BUILD ROUTE COLOR LOOKUP DICTIONARY ---
    route_colors = {}
    for _, r_row in subway_routes.iterrows():
        r_id = r_row['route_id']
        r_color = r_row.get('route_color', '7f8c8d')  # Fallback to grey if missing
        if pd.isna(r_color) or str(r_color).strip() == '':
            r_color = '7f8c8d'
        r_color = str(r_color).strip()
        # Add the hex prefix '#' if it's missing in the GTFS file
        if not r_color.startswith('#'):
            r_color = f"#{r_color}"
        route_colors[r_id] = r_color

    # Compute travel times in seconds
    subway_stop_times['arr_sec'] = subway_stop_times['arrival_time'].apply(time_to_seconds)
    subway_stop_times['dep_sec'] = subway_stop_times['departure_time'].apply(time_to_seconds)

    st_next = subway_stop_times.copy()
    st_next['stop_sequence'] -= 1  # shift to align with previous row

    merged = subway_stop_times[['trip_id', 'stop_sequence', 'stop_id', 'dep_sec']].merge(
        st_next[['trip_id', 'stop_sequence', 'stop_id', 'arr_sec']],
        on=['trip_id', 'stop_sequence'],
        suffixes=('_from', '_to')
    )
    merged = merged.rename(columns={'dep_sec': 'dep_sec_from', 'arr_sec': 'arr_sec_to'})
    merged['travel_time_sec'] = merged['arr_sec_to'] - merged['dep_sec_from']
    merged = merged[merged['travel_time_sec'] > 0]

    # --- 2. MERGE TRIP DETAILS TO PRESERVE ROUTE INFORMATION ---
    merged = merged.merge(subway_trip[['trip_id', 'route_id']], on='trip_id', how='left')

    # Median travel time per stop pair (and track route_id)
    edges = (
        merged
        .groupby(['stop_id_from', 'stop_id_to'])
        .agg(
            travel_time_sec=('travel_time_sec', 'median'),
            route_id=('route_id', 'first')
        )
        .reset_index()
    )

    # Build lookup structures
    stop_coords = (
        subway_stops
        .groupby('stop_name')[['stop_lat', 'stop_lon']]
        .mean()
    )
    allIds = dict(zip(subway_stops['stop_id'], subway_stops['stop_name']))
    allStops = set(subway_stops['stop_name'])

    # --- PROCESS TRUE GEOGRAPHIC SHAPES ---
    edge_shapes = {}
    if has_shapes and 'shape_id' in subway_trip.columns:
        shapes['shape_pt_lat'] = shapes['shape_pt_lat'].astype(float)
        shapes['shape_pt_lon'] = shapes['shape_pt_lon'].astype(float)
        shapes['shape_pt_sequence'] = shapes['shape_pt_sequence'].astype(int)

        # Pre-group shape coordinates by shape_id
        shape_dict = {}
        for shape_id, group in shapes.groupby('shape_id'):
            sorted_group = group.sort_values('shape_pt_sequence')
            shape_dict[shape_id] = sorted_group[['shape_pt_lat', 'shape_pt_lon']].values.tolist()

        # Stop ID to lat/lon quick dictionary
        stop_id_map = dict(zip(subway_stops['stop_id'], zip(subway_stops['stop_lat'], subway_stops['stop_lon'])))

        # Find one representative trip for each unique shape layout
        rep_trips = subway_trip.groupby('shape_id')['trip_id'].first().reset_index()

        for _, row in rep_trips.iterrows():
            sid = row['shape_id']
            tid = row['trip_id']
            if sid not in shape_dict: continue
            
            pts = shape_dict[sid]
            trip_stops = subway_stop_times[subway_stop_times['trip_id'] == tid].sort_values('stop_sequence')
            
            # Map each stop along the trip to its closest point index on the shape path
            matched_indices = []
            for _, s_row in trip_stops.iterrows():
                s_id = s_row['stop_id']
                s_lat, s_lon = stop_id_map.get(s_id, (None, None))
                if s_lat is None:
                    matched_indices.append(-1)
                    continue
                
                min_dist = float('inf')
                closest_idx = 0
                for idx, pt in enumerate(pts):
                    dist = (pt[0] - s_lat)**2 + (pt[1] - s_lon)**2
                    if dist < min_dist:
                        min_dist = dist
                        closest_idx = idx
                matched_indices.append(closest_idx)

            # Slice out the specific curved track segment between sequential stops
            for i in range(len(trip_stops) - 1):
                s_from = trip_stops.iloc[i]['stop_id']
                s_to = trip_stops.iloc[i + 1]['stop_id']
                idx_from = matched_indices[i]
                idx_to = matched_indices[i + 1]
                
                if idx_from != -1 and idx_to != -1:
                    if idx_from <= idx_to:
                        segment = pts[idx_from : idx_to + 1]
                    else:
                        segment = pts[idx_to : idx_from + 1][::-1]
                    edge_shapes[(s_from, s_to)] = segment

    # Build graph
    G = nx.Graph()
    name_to_int = {name: i for i, name in enumerate(sorted(allStops))}

    # Add nodes with stop_name, latitude, and longitude
    for name, int_id in name_to_int.items():
        lat = stop_coords.loc[name, 'stop_lat'] if name in stop_coords.index else None
        lon = stop_coords.loc[name, 'stop_lon'] if name in stop_coords.index else None
        G.add_node(int_id, stop_name=name, lat=lat, lon=lon)

    # Add edges with minimum weight, coordinate paths, and track colors
    for _, row in edges.iterrows():
        from_id = row['stop_id_from']
        to_id = row['stop_id_to']
        from_name = allIds.get(from_id)
        to_name   = allIds.get(to_id)
        if from_name is None or to_name is None:
            continue
        u = name_to_int[from_name]
        v = name_to_int[to_name]
        w = int(row['travel_time_sec'])
        
        # --- 3. EXTRACT ROUTE COLOR ---
        r_id = row['route_id']
        color = route_colors.get(r_id, '#7f8c8d')

        # Attempt to retrieve true curves, account for bidirectional lookup
        shape_coords = edge_shapes.get((from_id, to_id)) or edge_shapes.get((to_id, from_id))
        
        if shape_coords:
            # Self-correct shape orientation matching the direction of node u to node v
            lat_u, lon_u = G.nodes[u]['lat'], G.nodes[u]['lon']
            if lat_u is not None:
                d_start = (shape_coords[0][0] - lat_u)**2 + (shape_coords[0][1] - lon_u)**2
                d_end = (shape_coords[-1][0] - lat_u)**2 + (shape_coords[-1][1] - lon_u)**2
                if d_end < d_start:
                    shape_coords = shape_coords[::-1]
        else:
            # Fallback: Create straight connection path between both stations
            lat_u, lon_u = G.nodes[u]['lat'], G.nodes[u]['lon']
            lat_v, lon_v = G.nodes[v]['lat'], G.nodes[v]['lon']
            if lat_u is not None and lat_v is not None:
                shape_coords = [[lat_u, lon_u], [lat_v, lon_v]]

        # --- 4. ATTACH COLOR ATTRIBUTE TO NETWORK EDGE ---
        if G.has_edge(u, v):
            if w < G[u][v]['weight']:
                G[u][v]['weight'] = w
                if shape_coords:
                    G[u][v]['shape'] = shape_coords
                G[u][v]['color'] = color
        else:
            if shape_coords:
                G.add_edge(u, v, weight=w, shape=shape_coords, color=color)
            else:
                G.add_edge(u, v, weight=w, color=color)

    return G


def export_graph(G, out_path):
    """Export to a simple JSON node-link format."""
    data = nx.node_link_data(G)
    with open(out_path, 'w') as f:
        json.dump(data, f)
    print(f"Saved: {out_path}  ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")

if __name__ == '__main__':
    G = gtfs_to_graph(filePath, route_types={1})  # 1 = subway

    # Basic stats
    print(f"Stations : {G.number_of_nodes()}")
    print(f"Edges    : {G.number_of_edges()}")
    
    # Draw graph with line colors mapped dynamically
    edge_colors = [G[u][v].get('color', '#7f8c8d') for u, v in G.edges()]
    nx.draw_planar(G, with_labels=True, node_size=5, font_size=5, edge_color=edge_colors)
    plt.show()
    
    c = nx.shortest_path_length(G, source=52, target=69, weight='weight')
    print(f"Shortest travel time example: {c} seconds")
    export_graph(G, 'Examine-Vienna-Subway-Student-Project/subway_graph.json')