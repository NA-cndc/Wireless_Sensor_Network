"""
File chạy chính thức của Đồ án WSN.
Sử dụng ĐA TIẾN TRÌNH (Multiprocessing) để chạy song song 3 kịch bản bán kính.
"""

import json
import concurrent.futures
import multiprocessing
from wsn_sim.config import SimulationConfig
from wsn_sim.simulation import Simulation

def run_single_scenario(range_m: float, config_data: dict) -> float:
    """Hàm này sẽ được đẩy vào một nhân CPU riêng biệt để chạy độc lập."""
    print(f"\n[CORE Khởi động] >>> Bắt đầu kịch bản bán kính {range_m}m <<<")
    
    # Khởi tạo cấu hình và môi trường riêng cho từng core
    cfg = SimulationConfig.from_dict(config_data)
    sim = Simulation(cfg, current_range_m=range_m)
    
    # Chạy mô phỏng (Có thể tắt log in ra màn hình ở hàm _monitor_network nếu thấy quá rối)
    sim.run_for(5000.0)
    
    return range_m

def run_project():
    print("=" * 70)
    print(" KHỞI ĐỘNG HỆ THỐNG MÔ PHỎNG WSN - ĐẠI HỌC TÔN ĐỨC THẮNG")
    print(" Chế độ: ĐA TIẾN TRÌNH (MULTIPROCESSING) TỐI ƯU TỐC ĐỘ")
    print("=" * 70)
    
    # 1. Đọc dữ liệu thô từ file JSON
    with open("configs/default.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
    
    ranges = config_data.get("communication_ranges_m", [250.0, 300.0, 350.0])
    
    # 2. Phân bổ công việc cho các nhân CPU
    # ProcessPoolExecutor tự động tạo ra số lượng Process bằng số lượng kịch bản
    print(f"[HỆ THỐNG] Đang phân bổ {len(ranges)} kịch bản vào các nhân CPU...")
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=len(ranges)) as executor:
        # Gửi lệnh chạy hàm run_single_scenario đồng loạt
        futures = [executor.submit(run_single_scenario, r, config_data) for r in ranges]
        
        # Lắng nghe nhân CPU nào hoàn thành xong trước
        for future in concurrent.futures.as_completed(futures):
            completed_range = future.result()
            print(f"\n[HOÀN THÀNH] Kịch bản bán kính {completed_range}m đã ghi xong file CSV!")

    print("\n" + "=" * 70)
    print(" TOÀN BỘ MÔ PHỎNG ĐÃ HOÀN TẤT SIÊU TỐC!")
    print(" Hãy kiểm tra thư mục 'results' để lấy 3 file CSV.")
    print("=" * 70)

if __name__ == "__main__":
    # Dòng này bắt buộc phải có trên Windows để chạy Multiprocessing không bị lỗi
    multiprocessing.freeze_support()
    run_project()