"""Mô-đun phát hiện Selective Forwarding bằng Forwarding Ratio và EWMA Trust."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class NodeTrustState:
    """Trạng thái giám sát độ tin cậy của một nút chuyển tiếp (Relay)."""

    node_id: str
    trust_score: float = 1.0
    n_current_window: int = 0
    f_current_window: int = 0
    n_total: int = 0
    f_total: int = 0
    consecutive_low_windows: int = 0
    is_blacklisted: bool = False
    blacklisted_at_s: float | None = None
    isolation_until_s: float | None = None
    detection_timestamp_s: float | None = None
    trust_history: list[tuple[float, float]] = field(default_factory=list)


class TrustDetector:
    """Bộ phát hiện nút Selective Forwarding phân tán theo mô hình quan sát cục bộ (Watchdog).

    Công thức:
    - Forwarding ratio: FR_i = F_i / max(N_i, 1)
    - EWMA trust update: T_i(r) = beta * T_i(r-1) + (1 - beta) * FR_i(r)
    - Điều kiện cách ly: N_i >= N_min và T_i < tau liên tục trong K cửa sổ.
    """

    def __init__(
        self,
        beta_trust: float = 0.8,
        n_min: int = 5,
        tau_threshold: float = 0.85,
        k_consecutive: int = 3,
        t_isolation_s: float = 100.0,
        window_duration_s: float = 50.0,
        initial_trust: float = 1.0,
        watchdog_energy_j: float = 1e-6,
    ) -> None:
        self.beta_trust = float(beta_trust)
        self.n_min = int(n_min)
        self.tau_threshold = float(tau_threshold)
        self.k_consecutive = int(k_consecutive)
        self.t_isolation_s = float(t_isolation_s)
        self.window_duration_s = float(window_duration_s)
        self.initial_trust = float(initial_trust)
        self.watchdog_energy_j = float(watchdog_energy_j)

        self.nodes: dict[str, NodeTrustState] = {}
        self.total_observations: int = 0
        self.total_monitoring_energy_j: float = 0.0

    def _get_or_create(self, node_id: str) -> NodeTrustState:
        if node_id not in self.nodes:
            self.nodes[node_id] = NodeTrustState(
                node_id=node_id,
                trust_score=self.initial_trust,
            )
        return self.nodes[node_id]

    def record_forwarding_attempt(
        self,
        relay_id: str,
        forwarded: bool,
        packet_id: str = "",
        sim_time_s: float = 0.0,
    ) -> None:
        """Ghi nhận một lần quan sát hành vi chuyển tiếp của nút relay."""
        state = self._get_or_create(relay_id)
        state.n_current_window += 1
        state.n_total += 1
        if forwarded:
            state.f_current_window += 1
            state.f_total += 1

        self.total_observations += 1
        self.total_monitoring_energy_j += self.watchdog_energy_j

    def end_window(self, current_sim_time_s: float) -> list[str]:
        """Kết thúc một cửa sổ quan sát W: Cập nhật EWMA và trạng thái Blacklist."""
        newly_blacklisted: list[str] = []

        for node_id, state in self.nodes.items():
            if state.is_blacklisted and state.isolation_until_s is not None:
                if current_sim_time_s >= state.isolation_until_s:
                    state.is_blacklisted = False
                    state.consecutive_low_windows = 0
                    state.isolation_until_s = None

            if state.n_current_window >= self.n_min:
                fr = state.f_current_window / state.n_current_window
                state.trust_score = (
                    self.beta_trust * state.trust_score + (1.0 - self.beta_trust) * fr
                )
                state.trust_history.append((current_sim_time_s, state.trust_score))

                if state.trust_score < self.tau_threshold:
                    state.consecutive_low_windows += 1
                    if state.consecutive_low_windows >= self.k_consecutive and not state.is_blacklisted:
                        state.is_blacklisted = True
                        state.blacklisted_at_s = current_sim_time_s
                        state.isolation_until_s = current_sim_time_s + self.t_isolation_s
                        if state.detection_timestamp_s is None:
                            state.detection_timestamp_s = current_sim_time_s
                        newly_blacklisted.append(node_id)
                else:
                    state.consecutive_low_windows = 0
            else:
                pass

            state.n_current_window = 0
            state.f_current_window = 0

        return newly_blacklisted

    def get_blacklist(self) -> set[str]:
        """Trả về tập các node_id hiện đang bị cách ly (Blacklist)."""
        return {node_id for node_id, s in self.nodes.items() if s.is_blacklisted}

    def evaluate_detection(
        self,
        actual_attackers: set[str],
        total_sensor_ids: set[str],
        first_attack_time_s: float = 0.0,
    ) -> dict[str, Any]:
        """Đánh giá hiệu năng phát hiện theo ma trận nhầm lẫn (Confusion Matrix)."""
        detected = {node_id for node_id, s in self.nodes.items() if s.detection_timestamp_s is not None}
        benign_nodes = total_sensor_ids - actual_attackers

        tp = len(detected & actual_attackers)
        fp = len(detected & benign_nodes)
        fn = len(actual_attackers - detected)
        tn = len(benign_nodes - detected)

        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = (2.0 * precision * tpr) / (precision + tpr) if (precision + tpr) > 0 else 0.0

        delays = [
            self.nodes[nid].detection_timestamp_s - first_attack_time_s
            for nid in (detected & actual_attackers)
            if self.nodes[nid].detection_timestamp_s is not None
        ]
        avg_detection_delay_s = sum(delays) / len(delays) if delays else 0.0

        return {
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "TN": tn,
            "TPR": tpr,
            "FPR": fpr,
            "Precision": precision,
            "F1": f1,
            "avg_detection_delay_s": avg_detection_delay_s,
            "total_monitoring_energy_j": self.total_monitoring_energy_j,
            "total_observations": self.total_observations,
        }
