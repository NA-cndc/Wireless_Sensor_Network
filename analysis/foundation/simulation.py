"""Run the SimPy WSN to a time limit or the last sensor death."""

from __future__ import annotations

from bisect import bisect_right
from math import isfinite
from random import Random

import simpy

from analysis.foundation.config import SimulationConfig
from analysis.foundation.energy import RadioModel
from analysis.foundation.network import Network
from analysis.foundation.routing import RoutingEngine
from analysis.foundation.traffic import TrafficGenerator
from wsn_sim.topology import terminal_log_sample


class Simulation:
    def __init__(
        self, config: SimulationConfig | Network,
        current_range_m: float | simpy.Environment | None = None,
        routing_algo: str = "EMHR", env: simpy.Environment | None = None,
    ) -> None:
        if isinstance(current_range_m, simpy.Environment):
            if env is not None:
                raise TypeError("environment supplied twice")
            env, current_range_m = current_range_m, None
        if isinstance(config, Network):
            self.network = config
            self.config = config.config
            if current_range_m is not None:
                config.build_graph(current_range_m)
        else:
            self.config = config
            self.network = Network(config, current_range_m)
        self.env = env if env is not None else simpy.Environment()
        self.started_at = self.env.now
        self.routing_algo = routing_algo
        self.router = RoutingEngine(
            self.network, Random(f"MHR/{self.config.effective_traffic_seed}"), cache_mhr=True,
        )
        self.radio = RadioModel()
        self.traffic_gen = TrafficGenerator(
            self.env, self.network, self.router, self.radio, self.config, routing_algo,
            on_death=self._update_lifetime,
        )
        self.stop_reason: str | None = None
        self.milestones: dict[str, float | None] = dict.fromkeys(("FND", "HND", "LND", "functional_death"))
        self.initial_energy_j = sum(sensor.energy_j for sensor in self.network.sensors.values())
        self.alive_nodes = 0
        self.routable_nodes = 0
        self._lifetime_graph = self.network.graph
        self._update_lifetime()
        self.samples: list[dict[str, int | float]] = []
        self.log_finished = False
        self._snapshot()
        self.traffic_gen.start()

    def _update_lifetime(self) -> None:
        self.router.invalidate_mhr()
        self._lifetime_graph = self.network.graph
        self.alive_nodes = sum(sensor.is_alive for sensor in self.network.sensors.values())
        self.routable_nodes = len(self.network.routable_sensor_ids(alive_only=True))
        total = len(self.network.sensors)
        dead = total - self.alive_nodes
        elapsed = float(self.env.now - self.started_at)
        for key, reached in (
            ("FND", dead > 0), ("HND", dead * 2 >= total), ("LND", dead == total),
            ("functional_death", 0 < self.alive_nodes and 2 * self.routable_nodes < self.alive_nodes),
        ):
            if reached and self.milestones[key] is None:
                self.milestones[key] = elapsed

    def run_for(self, duration_s: float | None = None, *, finalize: bool | None = None) -> float:
        """Advance relatively with an explicit duration, or run the configured profile to completion."""
        if self.stop_reason is not None:
            return float(self.env.now)
        if finalize is None:
            finalize = duration_s is None
        duration = self.config.duration_s if duration_s is None else duration_s
        if not isfinite(duration) or duration <= 0:
            raise ValueError("duration_s must be positive and finite")
        target = (self.started_at if duration_s is None else self.env.now) + duration
        if target < self.env.now:
            raise ValueError("simulation already advanced beyond the configured duration")
        if finalize:
            self.traffic_gen.cutoff_s = target
        while self.milestones["LND"] is None and self.env.peek() <= target:
            timestamp = self.env.peek()
            self.env.step()
            if (
                not self.log_finished
                and self.milestones["LND"] is None
                and self.env.peek() != timestamp
                and self.traffic_gen.rounds != self.samples[-1]["Rounds"]
            ):
                self._snapshot()
        if self.milestones["LND"] is not None:
            self.stop_reason = "lnd"
        else:
            if self.env.now < target:
                self.env.run(until=target)
            if finalize:
                self.stop_reason = "duration_limit"
        if self.stop_reason is not None:
            self.traffic_gen.close_pending(f"simulation_end_{self.stop_reason}")
        self._snapshot()
        return float(self.env.now)

    def _snapshot(self) -> None:
        reachable = len(self.network.routable_sensor_ids(alive_only=True))
        if self._lifetime_graph is not self.network.graph or reachable != self.routable_nodes:
            self._update_lifetime()
        if self.log_finished:
            return
        traffic = self.traffic_gen
        rows = {
            "Time_s": float(self.env.now - self.started_at),
            "Alive_Nodes": self.alive_nodes,
            "Routable_Nodes": self.routable_nodes,
            "Total_Energy_J": sum(sensor.energy_j for sensor in self.network.sensors.values()),
            "Generated_Packets": len(traffic.generated_packets),
            "Delivered_Packets": len(traffic.delivered_packets),
            "Drop_NoRoute": traffic.drop_counts["unreachable"],
            "Drop_Dead": traffic.drop_counts["energy_depletion"],
            "Drop_Interf": traffic.drop_counts["natural_link_loss"],
            "Avg_Latency_s": traffic.total_latency_s / len(traffic.delivered_packets) if traffic.delivered_packets else 0.0,
            "Rounds": traffic.rounds,
            "Delivered_Payload_Bytes": traffic.delivered_bytes,
            "Drop_Queue": traffic.drop_counts["queue_drop"],
            "Drop_Cutoff": traffic.drop_counts["simulation_end_duration_limit"] + traffic.drop_counts["simulation_end_lnd"],
            "Pending_Packets": len(traffic.pending),
        }
        if self.samples and self.samples[-1]["Time_s"] == rows["Time_s"]:
            self.samples[-1] = rows
        else:
            self.samples.append(rows)
        self.log_finished = terminal_log_sample(self.alive_nodes, self.routable_nodes)

    def summary(self) -> dict:
        """Return metrics with explicit units and nulls for undefined or censored values."""
        traffic = self.traffic_gen
        generated, delivered = len(traffic.generated_packets), len(traffic.delivered_packets)
        elapsed = float(self.env.now - self.started_at)
        residual = sum(sensor.energy_j for sensor in self.network.sensors.values())
        consumed = self.initial_energy_j - residual
        payload_bits = 8 * traffic.delivered_bytes
        forward_counts = [sensor.forwarded_packets for sensor in self.network.sensors.values()]
        forward_squares = sum(count ** 2 for count in forward_counts)
        receive_times = [packet.delivered_at - self.started_at for packet in traffic.delivered_packets]
        return {
            "stop_reason": self.stop_reason,
            "elapsed_s": elapsed,
            "log_end_s": self.samples[-1]["Time_s"],
            "rounds": traffic.rounds,
            "alive_sensors": self.alive_nodes,
            "routable_sensors": self.routable_nodes,
            "generated_packets": generated,
            "delivered_packets": delivered,
            "dropped_packets": len(traffic.dropped_packets),
            "pending_packets": len(traffic.pending),
            "drop_reasons": {reason: traffic.drop_counts[reason] for reason in (
                "unreachable", "energy_depletion", "natural_link_loss", "queue_drop",
                "simulation_end_duration_limit", "simulation_end_lnd",
            )},
            "data_tx_attempts": traffic.tx_attempts,
            "route_changes": traffic.route_changes,
            "delivered_payload_bits": payload_bits,
            "milestones": {
                name: {"time_s": time, "payload_bits": None if time is None else (
                    bisect_right(receive_times, time) * 8 * self.config.packet_size_bytes
                )}
                for name, time in self.milestones.items()
            },
            "pdr_percent": 100 * delivered / generated if generated else None,
            "throughput_bps": payload_bits / elapsed if elapsed else None,
            "goodput_bps": payload_bits / elapsed if elapsed else None,
            "mean_offered_bps": generated * 8 * self.config.packet_size_bytes / elapsed if elapsed else None,
            "energy_consumed_j": consumed,
            "energy_initial_j": self.initial_energy_j,
            "energy_residual_j": residual,
            "energy_ledger_j": dict(traffic.energy_j),
            "energy_j_per_delivered_bit": consumed / payload_bits if payload_bits else None,
            "mean_hops": sum(packet.hop_count for packet in traffic.delivered_packets) / delivered if delivered else None,
            "mean_end_to_end_latency_s": traffic.total_latency_s / delivered if delivered else None,
            "relay_load_jain": sum(forward_counts) ** 2 / (len(forward_counts) * forward_squares) if forward_squares else None,
        }
