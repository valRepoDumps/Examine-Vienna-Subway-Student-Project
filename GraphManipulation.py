import networkx as nx
import json
import math
import folium
import streamlit as st
from streamlit_folium import st_folium

maxStations = 100
fileLocation = "subway_graph.json"

# Demo-only gate for the admin tools.
ADMIN_PASSWORD = "admin123"

# ── Distance helpers ───────────────────────────────────────────────────────────

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_nearest_station(clicked_lat, clicked_lon, G):
    """Linearly scans all nodes to find the closest station."""
    lats = nx.get_node_attributes(G, 'lat')
    lons = nx.get_node_attributes(G, 'lon')
    
    nearest_node = None
    min_dist = float('inf')
    
    for node in G.nodes():
        lat, lon = lats.get(node), lons.get(node)
        if lat is not None and lon is not None:
            dist = _haversine_m(clicked_lat, clicked_lon, lat, lon)
            if dist < min_dist:
                min_dist = dist
                nearest_node = node
                
    return nearest_node, min_dist

def nid(n): return int(n)

def load_graph(in_path):
    with open(in_path, 'r') as f:
        data = json.load(f)
    return nx.node_link_graph(data)

def preCalcRouteFloydWarshall(G, transfer_penalty = 0):
    matrix = [[float('inf')] * maxStations for _ in range(maxStations)]
    routes = [[None]         * maxStations for _ in range(maxStations)]
    for n1 in G.nodes():
        for n2 in G.nodes():
            i, j = nid(n1), nid(n2)
            if n1 == n2:
                matrix[i][j] = 0
                routes[i][j] = [n1]
            elif G.has_edge(n1, n2):
                matrix[i][j] = G[n1][n2]['weight']
                routes[i][j] = [n1, n2]
    for mid in G.nodes():
        m = nid(mid)
        for n1 in G.nodes():
            i = nid(n1)
            if n1 == mid: continue
            for n2 in G.nodes():
                if n2 == mid or n1 == n2: continue
                j = nid(n2)
                # check (n1 -> mid) and (mid -> n2) exist
                if matrix[i][m] != float('inf') and matrix[m][j] != float('inf'):
                    # if transfer penalty should be added
                    penalty = 0
                    if transfer_penalty > 0:
                        # find the incoming line color and outgoing line color
                        incoming_pred = routes[i][m][-2]
                        outgoing_succ = routes[m][j][1]
                        
                        inc_color = G[incoming_pred][mid].get('color')
                        out_color = G[mid][outgoing_succ].get('color')
                        
                        # if the colors exist and don't match, the passenger is swapping trains!
                        if inc_color and out_color and inc_color != out_color:
                            penalty = transfer_penalty

                    if matrix[i][j] > matrix[i][m] + matrix[m][j] + penalty:
                        matrix[i][j] = matrix[i][m] + matrix[m][j]
                        routes[i][j] = routes[i][m][:-1] + routes[m][j]
    return matrix, routes


def delete_route_edges(G, route_nodes, history):
    """Removes every track (edge) that makes up a given route."""
    if not route_nodes or len(route_nodes) < 2:
        return G, history
    for i in range(len(route_nodes) - 1):
        u, v = route_nodes[i], route_nodes[i + 1]
        if G.has_edge(u, v):
            history.append(("edge", (u, v, dict(G[u][v]))))
            G.remove_edge(u, v)
    return G, history

@st.cache_data(show_spinner=False)
def build_folium_map(graph_json_str, start_node=None, end_node=None, route_nodes=None):
    G = nx.node_link_graph(json.loads(graph_json_str))
    lats   = nx.get_node_attributes(G, 'lat')
    lons   = nx.get_node_attributes(G, 'lon')
    names  = nx.get_node_attributes(G, 'stop_name')
    shapes = nx.get_edge_attributes(G, 'shape')
    times  = nx.get_edge_attributes(G, 'weight')
    colors = nx.get_edge_attributes(G, 'color')

    route_set = set(route_nodes) if route_nodes else set()
    route_edges = set()
    route_nodes_list = list(route_nodes) if route_nodes else []
    if route_nodes_list and len(route_nodes_list) > 1:
        for i in range(len(route_nodes_list) - 1):
            route_edges.add((route_nodes_list[i], route_nodes_list[i+1]))
            route_edges.add((route_nodes_list[i+1], route_nodes_list[i]))

    fmap = folium.Map(location=[48.210033, 16.363449], zoom_start=12)

    # Draw edges — highlight route edges in yellow
    for edge in G.edges():
        u, v  = edge
        time  = times.get(edge, "?")
        tooltip = (
            f"<div style='font-family:Arial;font-size:12px'>"
            f"<b>🚇 Track</b> {u} → {v}<br/>"
            f"<span style='color:#e74c3c'><b>⏱ Travel time:</b> {time}</span></div>"
        )
        if edge in shapes:
            is_route_edge = (u, v) in route_edges
            folium.PolyLine(
                locations=shapes[edge],
                tooltip=tooltip,
                color="#f39c12" if is_route_edge else colors.get(edge, "#999999"),
                weight=14 if is_route_edge else 10,
                opacity=1.0 if is_route_edge else 0.5,
            ).add_to(fmap)

    # Draw station markers
    for station in G.nodes():
        lat, lon = lats.get(station), lons.get(station)
        if lat is None: continue
        name = names.get(station, str(station))

        if station == start_node:
            color, fill_color, radius, label = "#27ae60", "#2ecc71", 18, f"🟢 START: {name}"
        elif station == end_node:
            color, fill_color, radius, label = "#c0392b", "#e74c3c", 18, f"🔴 END: {name}"
        elif station in route_set:
            color, fill_color, radius, label = "#e67e22", "#f39c12", 14, f"🔶 {name}"
        else:
            color, fill_color, radius, label = "#2980b9", "#3498db", 12, name

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            popup=folium.Popup(f"<b>{label}</b><br/>ID: {station}", max_width=200),
            tooltip=label,
            color=color, fill=True, fill_color=fill_color,
            fill_opacity=0.9 if station in (start_node, end_node) or station in route_set else 0.8,
        ).add_to(fmap)

    return fmap

def parseCmd(cmd, G, history):
    """Parses text commands and updates the base structure."""
    parts = cmd.strip().split()
    if not parts: return G, history, None
    
    action = parts[0].lower()

    if action == 'drop':
        if len(parts) < 2:
            st.sidebar.error("Missing argument for drop (edge/node)")
            return G, history, None

        if parts[1] == 'edge' and len(parts) >= 4:
            u, v = int(parts[2]), int(parts[3])
            if G.has_edge(u, v):
                history.append(("edge", (u, v, dict(G[u][v]))))
                G.remove_edge(u, v)
                st.sidebar.success(f"Removed edge: {u} → {v}")
            else:
                st.sidebar.warning(f"Edge {u} → {v} not found")
        elif parts[1] == 'node' and len(parts) >= 3:
            node_to_remove = int(parts[2])
            if G.has_node(node_to_remove):
                node_attrs = dict(G.nodes[node_to_remove])
                connected_edges = []
                for nbr in list(G.neighbors(node_to_remove)):
                    connected_edges.append((node_to_remove, nbr, dict(G[node_to_remove][nbr])))
                
                history.append(("node", (node_to_remove, node_attrs, connected_edges)))
                G.remove_node(node_to_remove)
                st.sidebar.success(f"Removed node: {node_to_remove}")
            else:
                st.sidebar.warning(f"Node {node_to_remove} not found")
        else:
            st.sidebar.error(f"Unknown drop command syntax: {cmd}")

    elif action == 'restore':
        if not history:
            st.sidebar.warning("No actions left in history to restore.")
            return G, history, None
        
        type_restored, payload = history.pop()
        
        if type_restored == "edge":
            u, v, attrs = payload
            G.add_edge(u, v, **attrs)
            st.sidebar.success(f"Restored edge: {u} → {v}")
        elif type_restored == "node":
            node_id, node_attrs, edges = payload
            G.add_node(node_id, **node_attrs)
            for u, v, edge_attrs in edges:
                G.add_edge(u, v, **edge_attrs)
            st.sidebar.success(f"Restored node: {node_id} along with its connected tracks.")

    elif action == 'find' and len(parts) >= 4:
        try:
            u, v = int(parts[2]), int(parts[3])
            if not G.has_node(u) or not G.has_node(v):
                st.sidebar.error(f"One or both stations ({u}, {v}) do not exist in the current graph.")
                return G, history, None
            
            # Note: This checks via standard matrix inside parseCmd wrapper
            r = st.session_state.matrix[u][v]
            if r is None:
                st.sidebar.error(f"No path exists between {u} and {v}")
            return G, history, {"start": u, "end": v}
        except ValueError:
            st.sidebar.error("Station IDs must be integers.")
    else:
        st.sidebar.error(f"Unknown command: {cmd}")
        
    return G, history, None

st.set_page_config(page_title="Subway Graph Explorer", layout="wide")
st.title("🚇 Subway Graph Explorer")

# ── Init session state ─────────────────────────────────────────────────────────
if "G" not in st.session_state:
    st.session_state.G = load_graph(fileLocation)
    # Calculate both matrices concurrently right at startup
    st.session_state.matrixFast, st.session_state.routesFast = preCalcRouteFloydWarshall(st.session_state.G, transfer_penalty=0)
    st.session_state.matrixFewestTrainChange, st.session_state.routesFewestTrainChange = preCalcRouteFloydWarshall(st.session_state.G, transfer_penalty=9999)
    st.session_state.history = []

st.session_state.setdefault("start_node", None)
st.session_state.setdefault("end_node",   None)
st.session_state.setdefault("click_mode", "off")
st.session_state.setdefault("route_nodes", None)
st.session_state.setdefault("route_dist",  None)
st.session_state.setdefault("last_processed_click", None)
st.session_state.setdefault("is_admin", False)
st.session_state.setdefault("role_choice", "👤 User")

G = st.session_state.G
names = nx.get_node_attributes(G, 'stop_name')
history = st.session_state.history

# ── Sidebar: role switch ───────────────────────────────────────────────────────
st.sidebar.header("🔑 Mode")
role_choice = st.sidebar.radio(
    "Select mode",
    ["👤 User", "🛠️ Admin"],
    index=0 if st.session_state.role_choice == "👤 User" else 1,
    horizontal=True,
)
st.session_state.role_choice = role_choice

if role_choice == "🛠️ Admin" and not st.session_state.is_admin:
    admin_pwd = st.sidebar.text_input("Admin password", type="password", key="admin_pwd_input")
    if st.sidebar.button("Unlock Admin", use_container_width=True):
        if admin_pwd == ADMIN_PASSWORD:
            st.session_state.is_admin = True
            st.rerun()
        else:
            st.sidebar.error("Incorrect password.")

is_admin = (role_choice == "🛠️ Admin") and st.session_state.is_admin

if role_choice == "🛠️ Admin" and is_admin:
    st.sidebar.success("✅ Admin tools unlocked")
elif role_choice == "👤 User":
    st.caption("👤 **User mode** — choose a start and end station to create a route.")

st.sidebar.divider()

# ── NEW CODE: Sidebar Routing Optimization Toggle ──────────────────────────────────
st.sidebar.header("🎛️ Routing Preference")
route_pref = st.sidebar.radio(
    "Optimize route for:",
    ["⚡ Shortest Total Time", "🛋️ Fewest Train Changes"],
    index=0
)

# Set runtime active matrix and routing tables dynamically based on toggle choice
if route_pref == "⚡ Shortest Total Time":
    matrix = st.session_state.matrixFast
    routes = st.session_state.routesFast
else:
    matrix = st.session_state.matrixFewestTrainChange
    routes = st.session_state.routesFewestTrainChange

st.sidebar.divider()

# ── Sidebar: graph commands (admin only) ───────────────────────────────────────
if is_admin:
    st.sidebar.header("⚙️ Graph Commands")
    st.sidebar.markdown("- `drop edge U V`\n- `drop node N`\n- `restore` *(Undo last drop)*\n- `find route U V`")
    cmd_input = st.sidebar.text_input("Enter command:")
    cmd_col1, cmd_col2 = st.sidebar.columns(2)
    
    if cmd_col1.button("Run", use_container_width=True):
        G, history, command_result = parseCmd(cmd_input, G, history)
        st.session_state.G = G
        st.session_state.history = history
        
        # Core fix: recalculate BOTH matrix instances when topology adjustments are made
        st.session_state.matrixFast, st.session_state.routesFast = preCalcRouteFloydWarshall(G, 0)
        st.session_state.matrixFewestTrainChange, st.session_state.routesFewestTrainChange = preCalcRouteFloydWarshall(G, 9999)

        if command_result is not None:
            st.session_state.start_node = command_result["start"]
            st.session_state.end_node = command_result["end"]
            s, e = command_result["start"], command_result["end"]
            st.session_state.route_nodes = routes[s][e]
            st.session_state.route_dist = matrix[s][e]
        else:
            if st.session_state.start_node not in G: st.session_state.start_node = None
            if st.session_state.end_node not in G: st.session_state.end_node = None
            st.session_state.route_nodes = None
        st.rerun()
        
    if cmd_col2.button("↩️ Undo", use_container_width=True, disabled=not history):
        G, history, _ = parseCmd("restore", G, history)
        st.session_state.G = G
        st.session_state.history = history
        
        # Core fix: recalculate BOTH matrix profiles on structural restore commands
        st.session_state.matrixFast, st.session_state.routesFast = preCalcRouteFloydWarshall(G, 0)
        st.session_state.matrixFewestTrainChange, st.session_state.routesFewestTrainChange = preCalcRouteFloydWarshall(G, 9999)
        st.rerun()

    st.sidebar.divider()

# ── Sidebar: station selection (both modes) ────────────────────────────────────
st.sidebar.header("🗺️ Locate a Route" if is_admin else "🗺️ Station Selection")

col1, col2, col3 = st.sidebar.columns(3)
if col1.button("🟢 Set Start", use_container_width=True):
    st.session_state.click_mode = "start"
if col2.button("🔴 Set End", use_container_width=True):
    st.session_state.click_mode = "end"
if col3.button("⬜ Off", use_container_width=True):
    st.session_state.click_mode = "off"

mode = st.session_state.click_mode
mode_labels = {"off": "⬜ Off", "start": "🟢 Selecting START station", "end": "🔴 Selecting END station"}
st.sidebar.info(f"Click mode: **{mode_labels[mode]}**")

s_name = names.get(st.session_state.start_node, "—") if st.session_state.start_node is not None else "—"
e_name = names.get(st.session_state.end_node,   "—") if st.session_state.end_node is not None else "—"
st.sidebar.markdown(f"**Start:** 🟢 {s_name}")
st.sidebar.markdown(f"**End:** 🔴 {e_name}")

if st.sidebar.button("🔍 Find Route", use_container_width=True,
                     disabled=(st.session_state.start_node is None or st.session_state.end_node is None)):
    s = int(st.session_state.start_node)
    e = int(st.session_state.end_node)
    r = routes[s][e]
    d = matrix[s][e]
    if r is None or d == float('inf'):
        st.session_state.route_nodes = None
        st.session_state.route_dist  = None
        st.sidebar.error("No path exists between these stations.")
    else:
        st.session_state.route_nodes = r
        st.session_state.route_dist  = d

if st.sidebar.button("🗑️ Clear Selection", use_container_width=True):
    st.session_state.start_node  = None
    st.session_state.end_node    = None
    st.session_state.route_nodes = None
    st.session_state.route_dist  = None
    st.session_state.click_mode  = "off"
    st.rerun()

# ── Map ────────────────────────────────────────────────────────────────────────
st.subheader("🗺️ Map")

if mode != "off":
    st.info(f"{'🟢 Click the map to select the **START** station.' if mode == 'start' else '🔴 Click the map to select the **END** station.'}")

graph_json_str = json.dumps(nx.node_link_data(G))
fmap = build_folium_map(
    graph_json_str,
    start_node=st.session_state.start_node,
    end_node=st.session_state.end_node,
    route_nodes=tuple(st.session_state.route_nodes) if st.session_state.route_nodes else None,
)

map_data = st_folium(fmap, width=900, height=600, returned_objects=["last_clicked"])

# ── Handle click ───────────────────────────────────────────────────────────────
if mode != "off" and map_data and map_data.get("last_clicked"):
    click = map_data["last_clicked"]
    click_key = (click["lat"], click["lng"])

    if click_key != st.session_state.last_processed_click:
        st.session_state.last_processed_click = click_key

        nearest, dist = find_nearest_station(click["lat"], click["lng"], G)
        
        if nearest is not None:
            if mode == "start" and nearest != st.session_state.start_node:
                st.session_state.start_node  = nearest
                st.session_state.route_nodes = None
                st.session_state.route_dist  = None
                st.rerun()
            elif mode == "end" and nearest != st.session_state.end_node:
                st.session_state.end_node    = nearest
                st.session_state.route_nodes = None
                st.session_state.route_dist  = None
                st.rerun()

# ── Route result ───────────────────────────────────────────────────────────────
if st.session_state.route_nodes is not None:
    rn = st.session_state.route_nodes
    rd = st.session_state.route_dist
    st.success(f"✅ Route found ({route_pref}) — **{len(rn)} stations**, total routing cost value: **{rd}**")

    if is_admin:
        if st.button("🗑️ Delete This Route (Admin)", type="primary"):
            G, history = delete_route_edges(G, rn, history)
            st.session_state.G = G
            st.session_state.history = history
            
            # Recalculate profiles on route deletions
            st.session_state.matrixFast, st.session_state.routesFast = preCalcRouteFloydWarshall(G, 0)
            st.session_state.matrixFewestTrainChange, st.session_state.routesFewestTrainChange = preCalcRouteFloydWarshall(G, 9999)
            
            st.session_state.route_nodes = None
            st.session_state.route_dist  = None
            st.rerun()

    st.markdown("### 🛤️ Route Details")
    cols = st.columns([1, 6])
    for i, node in enumerate(rn):
        node_name = names.get(node, f"Station {node}")
        with cols[0]:
            if i == 0:
                st.markdown("🟢 **Start**")
            elif i == len(rn) - 1:
                st.markdown("🔴 **End**")
            else:
                st.markdown(f"&nbsp;&nbsp;&nbsp;↓")
        with cols[1]:
            if i == 0 or i == len(rn) - 1:
                st.markdown(f"**{node_name}** (ID: {node})")
            else:
                leg_time = G[rn[i-1]][node].get('weight', '?') if G.has_edge(rn[i-1], node) else '?'
                st.markdown(f"{node_name} (ID: {node}) — *+{leg_time} sec*")

    st.markdown(f"**Full node list:** `{rn}`")
elif st.session_state.start_node is not None and st.session_state.end_node is not None:
    st.info("Both stations selected — press **🔍 Find Route** in the sidebar.")