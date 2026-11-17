"""Module điều phối chính của mô phỏng WSN bằng SimPy (Đã hợp nhất)."""

from __future__ import annotations
import simpy
import os
import csv
from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.traffic import TrafficGenerator
from wsn_sim.energy import RadioModel

class Simulation:
    def __init__(self, config: SimulationConfig, current_range_m: float, routing_algo: str = "EMHR", env: simpy.Environment | None = None) -> None:
        self.config = config
        self.env = env if env is not None else simpy.Environment()
        self.network = Network(self.config)
        self.network.build_graph(range_m=current_range_m) 
        self.router = RoutingEngine(self.network)
        self.radio = RadioModel()
        self.routing_algo = routing_algo
        
        self.traffic_gen = TrafficGenerator(env=self.env, network=self.network, router=self.router, radio=self.radio, config=self.config, routing_algo=self.routing_algo)
        self.traffic_gen.start()
        self.env.process(self._monitor_network())

    def run_for(self, duration_s: float) -> float:
        if duration_s <= 0:
            raise ValueError("Thời gian mô phỏng (duration_s) phải lớn hơn 0")
        print(f"\n[MÔ PHỎNG] Tua nhanh hệ thống thêm {duration_s} giây...")
        self.env.run(until=self.env.now + duration_s)
        self._print_summary()
        return float(self.env.now)

    def _monitor_network(self):
        import csv
        from pathlib import Path
        import networkx as nx

        # Neo đường dẫn tuyệt đối về Wireless_Sensor_Network/results/csv
        project_root = Path(__file__).resolve().parents[2]
        csv_dir = project_root / "results" / "csv"
        csv_dir.mkdir(parents=True, exist_ok=True)

        csv_filename = csv_dir / f"simulation_log_{self.routing_algo}_range_{int(self.network.communication_range_m)}m.csv"

        with open(csv_filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Time_s", "Alive_Nodes", "Routable_Nodes", "Total_Energy_J", 
                "Generated_Packets", "Delivered_Packets", 
                "Drop_NoRoute", "Drop_Dead", "Drop_Interf", "Avg_Latency_s"
            ])
            
            while True:
                alive_sensor_ids = [s_id for s_id, s in self.network.sensors.items() if s.is_alive]
                alive_nodes = len(alive_sensor_ids)
                total_energy = sum(s.energy_j for s in self.network.sensors.values())
                
                valid_nodes = set(alive_sensor_ids + list(self.network.sinks.keys()))
                valid_graph = self.network.graph.subgraph(valid_nodes)
                
                routable_nodes = 0
                sink_ids = set(self.network.sinks.keys())
                for component in nx.connected_components(valid_graph):
                    if component & sink_ids:
                        routable_nodes += len(component - sink_ids)
                        
                gen_count = len(self.traffic_gen.generated_packets)
                deliv_count = len(self.traffic_gen.delivered_packets)
                
                drop_noroute = sum(1 for p in self.traffic_gen.dropped_packets if p.drop_reason == "NO_ROUTE")
                drop_dead = sum(1 for p in self.traffic_gen.dropped_packets if p.drop_reason == "NODE_DEAD_MID_FLIGHT")
                drop_interf = sum(1 for p in self.traffic_gen.dropped_packets if p.drop_reason == "ENVIRONMENTAL_INTERFERENCE")
                
                avg_latency = sum(self.traffic_gen.delivered_latencies) / deliv_count if deliv_count > 0 else 0.0
                
                print(f"[{self.routing_algo}-{int(self.network.communication_range_m)}m | {self.env.now:05.1f}s] Tới: {deliv_count} | Lỗi Tuyến: {drop_noroute} | Chết giữa chừng: {drop_dead} | Nhiễu: {drop_interf}")
                
                writer.writerow([
                    round(self.env.now, 1), alive_nodes, routable_nodes, round(total_energy, 4), 
                    gen_count, deliv_count, drop_noroute, drop_dead, drop_interf, round(avg_latency, 5)
                ])
                file.flush() 
                
                if alive_nodes == 0 or routable_nodes == 0:
                    break
                yield self.env.timeout(10.0)

    def _print_summary(self):
        total_generated = len(self.traffic_gen.generated_packets)
        alive_nodes = len([s for s in self.network.sensors.values() if s.is_alive])
        total_sensors = len(self.network.sensors)
        print("-" * 40)
        print(f"[TẠM DỪNG] Tại giây thứ {self.env.now:.1f} ({self.routing_algo})")
        print(f" -> Cảm biến còn sống : {alive_nodes}/{total_sensors}")
        print(f" -> Gói tin đã sinh   : {total_generated}")
        print("-" * 40)