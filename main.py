# main.py
from topology import create_wsn_topology, visualize_network

if __name__ == "__main__":
    print("[HỆ THỐNG] Đang khởi tạo topology mạng...")
    wsn_graph = create_wsn_topology()
    
    print(f"Tổng số Nodes (kể cả trạm ảo): {wsn_graph.number_of_nodes()}")
    print(f"Tổng số Liên kết khả thi: {wsn_graph.number_of_edges()}")
    
    print("[HỆ THỐNG] Đang hiển thị đồ thị...")
    visualize_network(wsn_graph)