import zipfile
import pandas as pd
import os
import json
from datetime import datetime
import networkx as nx
import matplotlib.pyplot as plt

filePath = "gtfs_path.zip"


def time_to_seconds(t):
    """Convert HH:MM:SS to seconds (handles times > 24h in GTFS)."""
    h, m, s = map(int, t.strip().split(':'))
    return h * 3600 + m * 60 + s

def gtfs_to_graph(gtfs_folder, route_types={1}):
    """
    gtfs_folder: path to the folder containing stops.txt, routes.txt, etc.
    """

    def read(name):
        # Check if gtfs_folder is a zip file
        if zipfile.is_zipfile(gtfs_folder):
            with zipfile.ZipFile(gtfs_folder, 'r') as z:
                # Walk zip contents in case files are in a subfolder
                for zip_path in z.namelist():
                    if zip_path.endswith(name):
                        with z.open(zip_path) as f:
                            return pd.read_csv(f, dtype=str)
                raise FileNotFoundError(f"{name} not found in {gtfs_folder}")

    #getting dataframes.
    routes     = read('routes.txt')
    trips      = read('trips.txt')
    stop_times = read('stop_times.txt')
    stops      = read('stops.txt')

    #Converting int stuff to int. 
    routes['route_type'] = routes['route_type'].astype(int)
    stop_times['stop_sequence'] = stop_times['stop_sequence'].astype(int)

    #filtering all the dataframes to only include subways. 
    subway_routes = routes[routes['route_type'].isin(route_types)].copy()
    subway_trip = trips[trips['route_id'].isin(subway_routes['route_id'])].copy()

    subway_stop_times = stop_times[stop_times['trip_id'].isin(subway_trip["trip_id"])].copy()
    subway_stops = stops[stops['stop_id'].isin(subway_stop_times["stop_id"])]

    #compute travel time in sécs
    subway_stop_times['arr_sec'] = subway_stop_times['arrival_time'].apply(time_to_seconds)
    subway_stop_times['dep_sec'] = subway_stop_times['departure_time'].apply(time_to_seconds)

    st_next = subway_stop_times.copy()
    st_next['stop_sequence'] -= 1   # shift to align with previous row

    merged = subway_stop_times[['trip_id', 'stop_sequence', 'stop_id', 'dep_sec']].merge(
        st_next[['trip_id', 'stop_sequence', 'stop_id', 'arr_sec']],
        on=['trip_id', 'stop_sequence'],
        suffixes=('_from', '_to')
    )

    merged = merged.rename(columns={
        'dep_sec': 'dep_sec_from',
        'arr_sec': 'arr_sec_to'
    })

    merged['travel_time_sec'] = merged['arr_sec_to'] - merged['dep_sec_from']


    merged['travel_time_sec'] = merged['arr_sec_to'] - merged['dep_sec_from']
    merged = merged[merged['travel_time_sec'] > 0]  # drop negative/zero artefacts

    pd.set_option('display.max_columns', 15)
    pd.set_option('display.max_rows', 30)


    edges = (
        merged
        .groupby(['stop_id_from', 'stop_id_to'])['travel_time_sec']
        .median()
        .reset_index()
    )

    
    allStops = set(subway_stops['stop_name'])
    allIds = dict(zip(subway_stops['stop_id'], subway_stops['stop_name'])) #make a dict of stop_id:stop_name

    #building graph.
    G = nx.Graph()

    # Add nodes
    name_to_int = {name: i for i, name in enumerate(sorted(allStops))} 
    for name, int_id in name_to_int.items():
        G.add_node(int_id, stop_name = name)
    
    
    name_to_int = {name: i for i, name in enumerate(sorted(set(allIds.values())))} 
    
    # Add edges
    for _, row in edges.iterrows():
        u = name_to_int[allIds[row['stop_id_from']]]
        v = name_to_int[allIds[row['stop_id_to']]]
        w = int(row['travel_time_sec'])
        if (G.has_edge(u, v)) :
            G[u][v]['weight'] = min(G[u][v]['weight'], w) #ensure only min edge got added. 
        else:
            G.add_weighted_edges_from([(u,v,w)])


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
    nx.draw_planar(G, with_labels=True, node_size = 5, font_size=5)
    plt.show()
    c = nx.shortest_path_length(G, source=52, target=69, weight='weight')
    print(c)
    export_graph(G, 'subway_graph.json')

