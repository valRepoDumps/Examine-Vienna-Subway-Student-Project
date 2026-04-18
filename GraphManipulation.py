import networkx as nx
import matplotlib.pyplot as plt
import json
from pyvis.network import Network
maxStations = 100
fileLocation = "subway_graph.json"

###
### drop edge u v -> bo edge (u,v)
### find route u v -> tim quang duong di ngan nhat giua u, v
### find dist u v -> tim khoang cach ngan nhat giua u, v. 


def load_graph(in_path):
    """Load graph from JSON node-link format."""
    with open(in_path, 'r') as f:
        data = json.load(f)
    G = nx.node_link_graph(data)
    print(f"Loaded: {in_path}  ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")
    return G

def preCalcRouteFloydWarshall(G):
    def nodeToInt(node):
        return int(node)
    
    totalNodes = G.number_of_nodes()
    matrix = [[float('inf')] * maxStations for _ in range(maxStations)]

    routes = [[None] * maxStations for _ in range(maxStations)]
    #setting up
    for node1 in G.nodes():
        for node2 in G.nodes():
            node1id = nodeToInt(node1)
            node2id = nodeToInt(node2)


            if (node1 == node2):
                matrix[node1id][node2id] = 0
                routes[node1id][node2id] = [node1]
            elif (G.has_edge(node1, node2)):
                matrix[node1id][node2id] = G[node1][node2]['weight']
                routes[node1id][node2id] = [node1, node2]
            else:
                matrix[node1id][node2id] = float('inf')
    
    #performing floyd warshall.
    for midNode in G.nodes():
        midNodeid = nodeToInt(midNode)
        for node1 in G.nodes():
            node1id = nodeToInt(node1)
            if node1 == midNode: continue
            for node2 in G.nodes():
                if node2 == midNode: continue
                if (node1 == node2): continue
                node2id = nodeToInt(node2)
                
                if (matrix[node1id][node2id] > matrix[node1id][midNodeid] + 
                                               matrix[midNodeid][node2id]):
                    matrix[node1id][node2id] = matrix[node1id][midNodeid] + matrix[midNodeid][node2id]
                    routes[node1id][node2id] = routes[node1id][midNodeid][:-1] + routes[midNodeid][node2id]
                


    return (matrix, routes)

# Usage, change
G = load_graph(fileLocation)

matrix, routes = preCalcRouteFloydWarshall(G)

def draw_graph():
    labels = nx.get_node_attributes(G, 'stop_name')  # {int_id: 'Station Name', ...}
    
    pos = nx.planar_layout(G)
    nx.draw(G, pos, labels=labels, with_labels=True, 
            node_size=5, node_color='lightblue', font_size=8)
    
    plt.show()

def draw_graph2():
    # Create a deep copy so we don't mess up the original G
    visual_G = G.copy() 
    
    g = Network(height="1500px", width="100%", bgcolor="#222222", font_color="white")
    g.from_nx(visual_G)
    
    for e in g.edges:
        # Check if width exists to avoid KeyError, then modify
        if 'width' in e:
            e['width'] /= 10
    
    for n in g.nodes:
        # Use the copied node data
        n['label'] = f"{n.get('stop_name', 'Unknown')} ({n['id']})"

    g.save_graph("test.html")

def getNodeNamesAndIds():
    for node_id, data in G.nodes(data=True):
        print(f"[{node_id}] {data['stop_name']} ")

def getNodeEdges():
    for u, v, data in G.edges(data=True):
        print(f"{u} ({G.nodes[u]['stop_name']}) -> {v} ({G.nodes[v]['stop_name']}): {data}")


def parseCmd(cmd):
    """Parse command for dropping edges. Format: 'drop edge A B'"""
    global matrix, routes
    parts = cmd.strip().split()
    if len(parts) == 0: return

    # try:
    if parts[0] == 'drop' and len(parts) >= 2:

        if parts[1] == 'edge' and len(parts) >= 4:

            u, v = int(parts[2]), int(parts[3])
            if G.has_edge(u, v):
                G.remove_edge(u, v)
                print(f"Removed edge: {u} -> {v}")
                matrix, routes = preCalcRouteFloydWarshall(G)
            else:
                print(f"Edge {u} -> {v} not found")
        elif parts[1] == 'node' and len(parts) >= 3:

            node = int(parts[2])
            G.remove_node(node)
            matrix, routes = preCalcRouteFloydWarshall(G)
        else:
            print(f"Unknown command: {cmd}")
        
    elif parts[0] == 'find' and len(parts) >= 4:
        if parts[1] == 'route':
            u, v = int(parts[2]), int(parts[3])
            print(routes[u][v])
        elif parts[1] == 'dist':
            u, v = int(parts[2]), int(parts[3])
            print(matrix[u][v])

            # use to test. 
            # try:
            #     # Use 'travel_time_sec' instead of 'weight'
            #     dist = nx.shortest_path_length(G, source=u, target=v, weight='travel_time_sec')
            #     print(f"True dist: {dist}")
            # except nx.NetworkXNoPath:
            #     print("No path exists between these stations.")
        else:
            print(f"Unknown command: {cmd}")
    else:
        print(f"Unknown command: {cmd}")
    # except:
    #     print(f"Unknown command: {cmd}")
    

def test():
    for node1 in G.nodes():
        for node2 in G.nodes():
            if (matrix[node1][node2] != 
                nx.shortest_path_length(G, source=node1, target=node2, weight='weight')):
                print("FAILED!")
                return
            
    print("TEST SUCCEED!")

draw_graph2()
cmd = input("Get cmd: ")
while (cmd != '#'):
    parseCmd(cmd)
    draw_graph()
    cmd = input("Get cmd: ")