"""Module điều phối chính của mô phỏng WSN bằng SimPy (Đã hợp nhất)."""

from __future__ import annotations
import simpy

from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.traffic import TrafficGenerator
from wsn_sim.energy import RadioModel
import os
import csv

class Simulation:
    """Quản lý toàn bộ vòng đời và tiến trình mô phỏng mạng cảm biến."""

    def __init__(
        self, 
        config: SimulationConfig,
        current_range_m: float,  # Thêm tham số này
        env: simpy.Environment | None = None
    ) -> None:
        self.config = config
        self.env = env if env is not None else simpy.Environment()
        
        self.network = Network(self.config)
        self.network.build_graph(range_m=current_range_m) 
        
        self.router = RoutingEngine(self.network)
        self.radio = RadioModel()
        
        self.traffic_gen = TrafficGenerator(
            env=self.env, 
            network=self.network, 
            router=self.router,
            radio=self.radio,
            config=self.config
        )


        # Nạp sẵn các tiến trình chạy ngầm vào đồng hồ SimPy
        self.traffic_gen.start()
        self.env.process(self._monitor_network())

    def run_for(self, duration_s: float) -> float:
        """
        Tua nhanh mô phỏng thêm một khoảng thời gian.
        
        Args:
            duration_s: Số giây muốn chạy mô phỏng.
            
        Returns:
            Thời gian tuyệt đối của hệ thống sau khi chạy xong.
        """
        if duration_s <= 0:
            raise ValueError("Thời gian mô phỏng (duration_s) phải lớn hơn 0")
            
        print(f"\n[MÔ PHỎNG] Tua nhanh hệ thống thêm {duration_s} giây...")
        
        # Chạy đồng hồ hệ thống đến mốc thời gian (hiện tại + thời gian chạy thêm)
        self.env.run(until=self.env.now + duration_s)
        
        self._print_summary()
        return float(self.env.now)

    def _monitor_network(self):
        """Tiến trình giám sát: Ghi log TẤT CẢ chỉ số ra file CSV."""
        import os, csv
        
        os.makedirs("results", exist_ok=True)
        csv_filename = f"results/simulation_log_range_{int(self.network.communication_range_m)}m.csv"
        
        with open(csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            
            # [MỚI] Thêm cột số gói Đã sinh, Đến đích, Bị rớt, và Độ trễ trung bình
            writer.writerow([
                "Time_s", "Alive_Nodes", "Total_Energy_J", 
                "Generated_Packets", "Delivered_Packets", "Dropped_Packets", "Avg_Latency_s"
            ])
            
            while True:
                # Đếm số node và pin
                alive_nodes = len([s for s in self.network.sensors.values() if s.is_alive])
                total_energy = sum(s.energy_j for s in self.network.sensors.values())
                
                # Đếm số liệu gói tin
                gen_count = len(self.traffic_gen.generated_packets)
                deliv_count = len(self.traffic_gen.delivered_packets)
                drop_count = len(self.traffic_gen.dropped_packets)
                
                # Tính độ trễ trung bình của các gói ĐÃ ĐẾN ĐÍCH
                if deliv_count > 0:
                    avg_latency = sum(self.traffic_gen.delivered_latencies) / deliv_count
                else:
                    avg_latency = 0.0
                
                # In ra Terminal một phiên bản gọn gàng
                print(f"[{self.env.now:05.1f}s] Sống: {alive_nodes:3d} | Gửi: {gen_count} | Tới: {deliv_count} | Rớt: {drop_count} | Trễ: {avg_latency:.4f}s")
                
                # Ghi vào CSV
                writer.writerow([
                    round(self.env.now, 1), 
                    alive_nodes, 
                    round(total_energy, 4), 
                    gen_count, 
                    deliv_count, 
                    drop_count, 
                    round(avg_latency, 5)
                ])
                file.flush() 
                
                if alive_nodes == 0:
                    break
                    
                yield self.env.timeout(10.0)

    def _print_summary(self):
        """In báo cáo khi đồng hồ tạm dừng."""
        total_generated = len(self.traffic_gen.generated_packets)
        alive_nodes = len([s for s in self.network.sensors.values() if s.is_alive])
        
        print("-" * 40)
        print(f"[TẠM DỪNG] Tại giây thứ {self.env.now:.1f}")
        print(f" -> Cảm biến còn sống : {alive_nodes}/{self.config.num_sensors}")
        print(f" -> Gói tin đã sinh   : {total_generated}")
        print("-" * 40)