# topology.py
import math
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
import config

def generate_valid_positions(num_nodes, area_size, min_dist=5.0):
    """
    Sinh tọa độ ngẫu nhiên đảm bảo các nút cách nhau ít nhất min_dist (mét)
    """
    positions = []
    while len(positions) < num_nodes:
        new_pos = np.random.uniform(0, area_size, 2)
        # Kiểm tra khoảng cách với các nút đã sinh trước đó
        if all(math.dist(new_pos, p) >= min_dist for p in positions):
            positions.append(new_pos)
    return np.array(positions)

def create_wsn_topology():
    # Cố định Seed để kết quả có thể tái lập
    np.random.seed(config.SEED)
    
    # Bước 1: Sinh tổng cộng 457 vị trí không trùng lặp (cách nhau ít nhất 20m)
    total_nodes = config.NUM_SENSORS + config.NUM_SINKS
    all_positions = generate_valid_positions(total_nodes, config.AREA_SIZE, min_dist=20.0)
    
    # Cắt mảng (slice) để chia tọa độ cho Sensor và Sink
    sensors = all_positions[:config.NUM_SENSORS]
    sinks = all_positions[config.NUM_SENSORS:]
    
    G = nx.Graph()
    
    # Gán ID cho Sensor Node (từ 1 đến 450)
    for i, pos in enumerate(sensors):
        G.add_node(i + 1, pos=tuple(pos), type='sensor')
        
    # Gán ID cho Sink Node (từ 451 đến 457)
    for i, pos in enumerate(sinks):
        sink_id = config.NUM_SENSORS + i + 1
        G.add_node(sink_id, pos=tuple(pos), type='sink')
        
    # Bước 2: Xây dựng mạng kết nối dựa trên bán kính truyền (Euclid <= R)
    nodes = list(G.nodes(data=True))
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            n1_id, n1_data = nodes[i]
            n2_id, n2_data = nodes[j]
            
            dist = math.dist(n1_data['pos'], n2_data['pos'])
            
            if dist <= config.TX_RADIUS:
                if n1_data['type'] == 'sink' and n2_data['type'] == 'sink':
                    continue
                G.add_edge(n1_id, n2_id, distance=dist)
                
    # Bước 3: Thêm Virtual Super-Sink (ID: 0) để gom 7 Sink thật
    G.add_node(0, pos=(config.AREA_SIZE/2, config.AREA_SIZE/2), type='virtual_sink')
    for i in range(config.NUM_SINKS):
        sink_id = config.NUM_SENSORS + i + 1
        G.add_edge(0, sink_id, distance=0)
        
    return G

def visualize_network(G):
    plt.figure(figsize=(10, 10))
    pos = nx.get_node_attributes(G, 'pos')
    
    sensor_nodes = [n for n, attr in G.nodes(data=True) if attr['type'] == 'sensor']
    sink_nodes = [n for n, attr in G.nodes(data=True) if attr['type'] == 'sink']
    
    nx.draw_networkx_edges(G, pos, alpha=0.15, edge_color='gray')
    nx.draw_networkx_nodes(G, pos, nodelist=sensor_nodes, node_color='blue', node_size=15, label='Sensor')
    nx.draw_networkx_nodes(G, pos, nodelist=sink_nodes, node_color='red', node_size=100, node_shape='s', label='Sink Node')
    
    plt.title(f"Topology Mạng WSN ({config.NUM_SENSORS} Sensors, {config.NUM_SINKS} Sinks, R={config.TX_RADIUS}m)")
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.show()
    
def check_network_connectivity(G):
    """Kiểm tra các node bị cô lập và tính liên thông của mạng"""
    # 1. Tìm các node không có bất kỳ liên kết nào
    isolated_nodes = list(nx.isolates(G))
    if isolated_nodes:
        print(f"[CẢNH BÁO] Phát hiện {len(isolated_nodes)} node bị cô lập hoàn toàn: {isolated_nodes}")
    else:
        print("[OK] Không có node nào bị cô lập hoàn toàn.")
        
    # 2. Bỏ qua Virtual Sink (ID: 0) để đánh giá mạng lưới vật lý thực tế
    G_physical = G.copy()
    if G_physical.has_node(0):
        G_physical.remove_node(0)
    
    # 3. Phân tích các cụm liên thông (Connected Components)
    components = list(nx.connected_components(G_physical))
    if len(components) == 1:
        print("[OK] Mạng lưới liên thông hoàn hảo. Mọi sensor đều có đường truyền hợp lệ tới Sinks.")
    else:
        print(f"[CẢNH BÁO] Sóng vô tuyến không phủ kín! Mạng bị đứt gãy thành {len(components)} mảnh riêng biệt.")
        print(f" -> Mảnh lớn nhất chứa {len(max(components, key=len))} thiết bị.")