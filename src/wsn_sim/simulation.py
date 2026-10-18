'''SimPy orchestration, event measurements and run export.'''

from __future__ import annotations

import csv
import math
from collections.abc import Generator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import simpy

from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.models import PacketStatus
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.traffic import TrafficGenerator

TIMESERIES_COLUMNS = [
    'time_s',
    'event_seq',
    'alive_sensors',
    'dead_sensors',
    'total_energy_j',
    'generated_packets',
    'delivered_packets',
    'dropped_packets',
    'pending_packets',
    'reachable_sensors',
    'reachability_ratio',
    'reachability_state',
    'routing_eligible_sensors',
    'routing_eligible_ratio',
    'energy_feasible_sensors',
    'energy_feasible_ratio',
    'delivered_bytes',
    'delivered_payload_bytes',
    'snapshot_kind',
]

SERVICEABILITY_COLUMNS = [
    'time_s',
    'event_seq',
    'alive_sensors',
    'reachable_sensors',
    'reachability_ratio',
    'routing_eligible_sensors',
    'routing_eligible_ratio',
    'energy_feasible_sensors',
    'energy_feasible_ratio',
    'sample_kind',
]


@dataclass(slots=True)
class SimulationResult:
    simulated_time_s: float
    nodes: int
    sensors: int
    sinks: int
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_smoke_simulation(network: Network, duration_s: float) -> SimulationResult:
    sim = Simulation(network, enable_traffic=False)
    sim_time = sim.run_for(duration_s)
    return SimulationResult(
        simulated_time_s=sim_time,
        nodes=network.graph.number_of_nodes(),
        sensors=len(network.sensors),
        sinks=len(network.sinks),
    )


class Simulation:
    '''Manage one independent WSN simulation run.'''

    def __init__(
        self,
        target: Network | SimulationConfig,
        env: simpy.Environment | None = None,
        *,
        current_range_m: float | None = None,
        range_m: float | None = None,
        config: SimulationConfig | None = None,
        routing_algorithm: str = 'EMHR',
        alpha_energy: float = 0.20,
        enable_traffic: bool = True,
        csv_log_path: str | Path | None = None,
        quiet: bool = True,
        seed: int | None = None,
    ) -> None:
        self.env = env if env is not None else simpy.Environment()
        self.quiet = quiet
        self.csv_log_path = Path(csv_log_path) if csv_log_path else None
        self.requested_duration_s = 0.0
        self.event_seq_counter: int = 0
        self.reachability_history: list[dict[str, Any]] = []
        self.timeseries_snapshots: list[dict[str, Any]] = []
        self.serviceability_history: list[dict[str, Any]] = []
        self.serviceability_sample_interval_s = 10.0

        effective_range = range_m if current_range_m is None else current_range_m
        if isinstance(target, Network):
            self.network = target
            self.config = config if config is not None else target.config
            if (
                effective_range is not None
                and effective_range != self.network.communication_range_m
            ):
                self.network.build_graph(effective_range)
        elif isinstance(target, SimulationConfig):
            self.config = target
            selected_range = (
                effective_range
                if effective_range is not None
                else target.communication_ranges_m[0]
            )
            self.network = Network(self.config, communication_range_m=selected_range)
        else:
            raise TypeError(f'target must be Network or SimulationConfig, got {type(target)}')

        self.routing_algorithm = routing_algorithm.upper()
        if self.routing_algorithm not in {'MHR', 'EMHR'}:
            raise ValueError('routing_algorithm must be MHR or EMHR')
        self.alpha_energy = float(alpha_energy)
        self.traffic_seed = self.config.seed if seed is None else int(seed)

        self.router = RoutingEngine(
            self.network,
            algorithm=self.routing_algorithm,
            alpha_energy=self.alpha_energy,
            event_seq_provider=self.next_event_seq,
        )
        self.radio = RadioModel(
            death_callback=self._on_node_death,
            event_seq_provider=self.next_event_seq,
        )
        self.enable_traffic = enable_traffic
        self.traffic_gen: TrafficGenerator | None = None
        if self.enable_traffic:
            self.traffic_gen = TrafficGenerator(
                env=self.env,
                network=self.network,
                router=self.router,
                radio=self.radio,
                config=self.config,
                traffic_seed=self.traffic_seed,
                event_seq_provider=self.next_event_seq,
            )
            self.traffic_gen.start()

        self._record_reachability_event('initial')
        initial_snapshot = self._build_snapshot('initial')
        self.timeseries_snapshots.append(initial_snapshot)
        self.serviceability_history.append(
            self._serviceability_sample(initial_snapshot, 'initial')
        )
        if self.csv_log_path is not None:
            self._write_timeseries_csv(self.csv_log_path, self.timeseries_snapshots)
        self.env.process(self._monitor_network())

    def next_event_seq(self) -> int:
        self.event_seq_counter += 1
        return self.event_seq_counter

    def _record_reachability_event(
        self,
        trigger: str,
        death_node_id: str | None = None,
    ) -> None:
        snapshot = self.network.physical_reachability_snapshot(float(self.env.now))
        snapshot['trigger'] = trigger
        snapshot['death_node_id'] = death_node_id
        snapshot['event_seq'] = self.next_event_seq()
        self.reachability_history.append(snapshot)

    def _on_node_death(self, event: dict[str, Any]) -> None:
        self._record_reachability_event('node_death', str(event['node_id']))

    def _packet_partition(self) -> tuple[list[Any], list[Any], list[Any]]:
        packets = list(self.traffic_gen.generated_packets) if self.traffic_gen else []
        delivered = [
            packet for packet in packets if packet.status is PacketStatus.DELIVERED
        ]
        dropped = [
            packet
            for packet in packets
            if packet.status in (PacketStatus.DROPPED, PacketStatus.NO_ROUTE)
        ]
        pending = [
            packet
            for packet in packets
            if packet.status in (PacketStatus.CREATED, PacketStatus.IN_TRANSIT)
        ]
        return delivered, dropped, pending

    def _build_snapshot(self, snapshot_kind: str) -> dict[str, Any]:
        packets = list(self.traffic_gen.generated_packets) if self.traffic_gen else []
        delivered, dropped, pending = self._packet_partition()
        unique_delivered = list(
            {packet.packet_id: packet for packet in delivered}.values()
        )
        reachability = self.network.physical_reachability_snapshot(float(self.env.now))
        alive_count = reachability['alive_sensors']
        feasibility = self.router.transmission_feasibility_snapshot(
            radio=self.radio,
            packet_size_bytes=int(self.config.packet_size_bytes),
            time_s=float(self.env.now),
        )
        return {
            'time_s': float(self.env.now),
            'event_seq': self.next_event_seq(),
            'alive_sensors': alive_count,
            'dead_sensors': len(self.network.sensors) - alive_count,
            'total_energy_j': sum(
                sensor.energy_j for sensor in self.network.sensors.values()
            ),
            'generated_packets': len(packets),
            'delivered_packets': len(unique_delivered),
            'dropped_packets': len(dropped),
            'pending_packets': len(pending),
            'reachable_sensors': reachability['reachable_sensors'],
            'reachability_ratio': reachability['reachability_ratio'],
            'reachability_state': reachability['state'],
            'routing_eligible_sensors': feasibility['routing_eligible_sensors'],
            'routing_eligible_ratio': feasibility['routing_eligible_ratio'],
            'energy_feasible_sensors': feasibility['energy_feasible_sensors'],
            'energy_feasible_ratio': feasibility['energy_feasible_ratio'],
            'delivered_bytes': sum(packet.size_bytes for packet in unique_delivered),
            'delivered_payload_bytes': sum(
                packet.payload_size_bytes for packet in unique_delivered
            ),
            'snapshot_kind': snapshot_kind,
        }

    def _timeseries_for_export(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self.timeseries_snapshots]
        final = self._build_snapshot('final')
        if rows and rows[-1]['time_s'] == final['time_s']:
            rows[-1] = final
        else:
            rows.append(final)
        return rows

    @staticmethod
    def _serviceability_sample(
        snapshot: Mapping[str, Any], sample_kind: str
    ) -> dict[str, Any]:
        return {
            'time_s': snapshot['time_s'],
            'event_seq': snapshot['event_seq'],
            'alive_sensors': snapshot['alive_sensors'],
            'reachable_sensors': snapshot['reachable_sensors'],
            'reachability_ratio': snapshot['reachability_ratio'],
            'routing_eligible_sensors': snapshot['routing_eligible_sensors'],
            'routing_eligible_ratio': snapshot['routing_eligible_ratio'],
            'energy_feasible_sensors': snapshot['energy_feasible_sensors'],
            'energy_feasible_ratio': snapshot['energy_feasible_ratio'],
            'sample_kind': sample_kind,
        }

    def _serviceability_for_export(self) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self.serviceability_history]
        final_snapshot = self._build_snapshot('final')
        final = self._serviceability_sample(final_snapshot, 'final')
        if rows and rows[-1]['time_s'] == final['time_s']:
            rows[-1] = final
        else:
            rows.append(final)
        return rows

    def _serviceability_for_metrics(self) -> list[dict[str, Any]]:
        '''Return sampled history plus a read-only observation-end sample.'''
        rows = [dict(row) for row in self.serviceability_history]
        now = float(self.env.now)
        reachability = self.network.physical_reachability_snapshot(now)
        feasibility = self.router.transmission_feasibility_snapshot(
            radio=self.radio,
            packet_size_bytes=int(self.config.packet_size_bytes),
            time_s=now,
        )
        final = {
            'time_s': now,
            'alive_sensors': reachability['alive_sensors'],
            'reachable_sensors': reachability['reachable_sensors'],
            'reachability_ratio': reachability['reachability_ratio'],
            'routing_eligible_sensors': feasibility['routing_eligible_sensors'],
            'routing_eligible_ratio': feasibility['routing_eligible_ratio'],
            'energy_feasible_sensors': feasibility['energy_feasible_sensors'],
            'energy_feasible_ratio': feasibility['energy_feasible_ratio'],
            'sample_kind': 'final',
        }
        if rows and rows[-1]['time_s'] == now:
            rows[-1] = final
        else:
            rows.append(final)
        return rows

    @staticmethod
    def _write_rows(
        path: Path,
        fieldnames: Sequence[str],
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8') as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name) for name in fieldnames})

    def _write_timeseries_csv(
        self,
        path: Path,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self._write_rows(path, TIMESERIES_COLUMNS, rows)

    def smoke_process(self, timeout_s: float) -> Generator[simpy.Event, None, None]:
        if timeout_s <= 0:
            raise ValueError('timeout_s must be greater than zero')
        yield self.env.timeout(timeout_s)

    def run_for(self, duration_s: float) -> float:
        if duration_s <= 0:
            raise ValueError('duration_s must be greater than zero')
        self.requested_duration_s += float(duration_s)
        target_time = self.env.now + duration_s
        self.env.process(self.smoke_process(duration_s))
        self.env.run(until=target_time)
        if self.csv_log_path is not None:
            self._write_timeseries_csv(
                self.csv_log_path,
                self._timeseries_for_export(),
            )
        if not self.quiet and self.enable_traffic:
            self._print_summary()
        return float(self.env.now)

    def _monitor_network(self) -> Generator[simpy.Event, None, None]:
        while True:
            yield self.env.timeout(10.0)
            snapshot = self._build_snapshot('periodic')
            self.timeseries_snapshots.append(snapshot)
            self.serviceability_history.append(
                self._serviceability_sample(snapshot, 'periodic')
            )
            if self.csv_log_path is not None:
                self._write_timeseries_csv(
                    self.csv_log_path,
                    self.timeseries_snapshots,
                )
            if snapshot['alive_sensors'] == 0:
                return

    def _print_summary(self) -> None:
        metrics = self.get_metrics()
        print('-' * 40)
        print(f'[PAUSED] Simulation time: {self.env.now:.6f} s')
        print(
            f'Alive sensors: {metrics["alive_sensors"]}/{metrics["total_sensors"]}; '
            f'generated={metrics["generated_packets"]}; '
            f'delivered={metrics["delivered_packets"]}'
        )
        print('-' * 40)

    def get_metrics(self) -> dict[str, Any]:
        from wsn_sim.metrics import calculate_simulation_metrics

        if not self.traffic_gen:
            return {
                'simulated_time_s': float(self.env.now),
                'measurement_duration_s': float(self.env.now),
                'nodes': self.network.graph.number_of_nodes(),
                'sensors': len(self.network.sensors),
                'sinks': len(self.network.sinks),
            }
        return calculate_simulation_metrics(
            network=self.network,
            traffic_gen=self.traffic_gen,
            radio=self.radio,
            sim_time_s=float(self.env.now),
            router=self.router,
            reachability_history=self.reachability_history,
            serviceability_history=self._serviceability_for_metrics(),
            serviceability_sample_interval_s=self.serviceability_sample_interval_s,
        )

    def export_results(self, output_dir: str | Path) -> dict[str, Path]:
        from wsn_sim.storage import create_run_manifest, save_json

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        saved_files: dict[str, Path] = {}

        config_path = out_path / 'config.json'
        save_json(self.config.to_dict(), config_path)
        saved_files['config'] = config_path

        metrics_path = out_path / 'metrics.json'
        save_json(self.get_metrics(), metrics_path)
        saved_files['metrics'] = metrics_path

        nodes_path = out_path / 'nodes.csv'
        node_fields = [
            'node_id',
            'type',
            'x',
            'y',
            'initial_energy_j',
            'energy_j',
            'is_alive',
            'death_time_s',
            'generated_packets',
            'received_packets',
            'forwarded_packets',
            'dropped_packets',
            'tx_energy_total_j',
            'rx_energy_total_j',
        ]
        node_rows: list[dict[str, Any]] = []
        for sensor in self.network.sensors.values():
            node_rows.append(
                {
                    'node_id': sensor.node_id,
                    'type': 'sensor',
                    'x': sensor.x,
                    'y': sensor.y,
                    'initial_energy_j': sensor.initial_energy_j,
                    'energy_j': sensor.energy_j,
                    'is_alive': sensor.is_alive,
                    'death_time_s': sensor.death_time_s,
                    'generated_packets': sensor.generated_packets,
                    'received_packets': sensor.received_packets,
                    'forwarded_packets': sensor.forwarded_packets,
                    'dropped_packets': sensor.dropped_packets,
                    'tx_energy_total_j': sensor.tx_energy_total_j,
                    'rx_energy_total_j': sensor.rx_energy_total_j,
                }
            )
        for sink in self.network.sinks.values():
            node_rows.append(
                {
                    'node_id': sink.node_id,
                    'type': 'sink',
                    'x': sink.x,
                    'y': sink.y,
                    'initial_energy_j': 'unlimited',
                    'energy_j': 'unlimited',
                    'is_alive': True,
                    'death_time_s': None,
                    'generated_packets': 0,
                    'received_packets': sink.received_packet_count,
                    'forwarded_packets': 0,
                    'dropped_packets': 0,
                    'tx_energy_total_j': 0.0,
                    'rx_energy_total_j': 0.0,
                }
            )
        self._write_rows(nodes_path, node_fields, node_rows)
        saved_files['nodes'] = nodes_path

        topology_path = out_path / 'topology_edges.csv'
        topology_fields = ['source_id', 'target_id', 'distance_m']
        topology_rows: list[dict[str, Any]] = []
        ordered_edges = sorted(
            self.network.graph.edges(data=True),
            key=lambda edge: tuple(sorted((str(edge[0]), str(edge[1])))),
        )
        for left_id, right_id, attributes in ordered_edges:
            source_id, target_id = sorted((str(left_id), str(right_id)))
            distance_m = attributes.get('distance_m')
            if distance_m is None:
                left = self.network.graph.nodes[left_id]
                right = self.network.graph.nodes[right_id]
                distance_m = math.hypot(
                    float(left['x']) - float(right['x']),
                    float(left['y']) - float(right['y']),
                )
            topology_rows.append(
                {
                    'source_id': source_id,
                    'target_id': target_id,
                    'distance_m': distance_m,
                }
            )
        self._write_rows(topology_path, topology_fields, topology_rows)
        saved_files['topology_edges'] = topology_path

        packets_path = out_path / 'packets.csv'
        packet_fields = [
            'packet_id',
            'source_id',
            'sink_id',
            'sequence_number',
            'size_bytes',
            'payload_size_bytes',
            'created_at',
            'created_event_seq',
            'delivered_at',
            'delivered_event_seq',
            'dropped_at',
            'dropped_event_seq',
            'latency_s',
            'hop_count',
            'status',
            'drop_reason',
            'drop_category',
            'drop_detail',
            'drop_node_id',
            'route',
            'path',
        ]
        packet_rows: list[dict[str, Any]] = []
        packets = list(self.traffic_gen.generated_packets) if self.traffic_gen else []
        packets.sort(key=lambda packet: (packet.source_id, packet.sequence_number))
        for packet in packets:
            packet_rows.append(
                {
                    'packet_id': packet.packet_id,
                    'source_id': packet.source_id,
                    'sink_id': packet.sink_id,
                    'sequence_number': packet.sequence_number,
                    'size_bytes': packet.size_bytes,
                    'payload_size_bytes': packet.payload_size_bytes,
                    'created_at': packet.created_at,
                    'created_event_seq': packet.created_event_seq,
                    'delivered_at': packet.delivered_at,
                    'delivered_event_seq': packet.delivered_event_seq,
                    'dropped_at': packet.dropped_at,
                    'dropped_event_seq': packet.dropped_event_seq,
                    'latency_s': packet.latency_s,
                    'hop_count': len(packet.path) - 1,
                    'status': packet.status.value,
                    'drop_reason': packet.drop_reason,
                    'drop_category': packet.drop_category,
                    'drop_detail': packet.drop_detail,
                    'drop_node_id': packet.drop_node_id,
                    'route': '->'.join(packet.route),
                    'path': '->'.join(packet.path),
                }
            )
        self._write_rows(packets_path, packet_fields, packet_rows)
        saved_files['packets'] = packets_path

        route_events_path = out_path / 'route_events.csv'
        route_fields = [
            'time_s',
            'event_seq',
            'source_id',
            'packet_id',
            'current_node_id',
            'old_route',
            'new_route',
            'reason',
            'outcome',
        ]
        self._write_rows(route_events_path, route_fields, self.router.route_events)
        saved_files['route_events'] = route_events_path

        ledger_path = out_path / 'energy_ledger.csv'
        ledger_fields = [
            'time_s',
            'event_seq',
            'packet_id',
            'sender_id',
            'receiver_id',
            'distance_m',
            'tx_energy_j',
            'rx_energy_j',
            'success',
            'reason',
            'sender_energy_before',
            'sender_energy_after',
            'receiver_energy_before',
            'receiver_energy_after',
        ]
        self._write_rows(ledger_path, ledger_fields, self.radio.energy_ledger)
        saved_files['energy_ledger'] = ledger_path

        deaths_path = out_path / 'node_deaths.csv'
        death_fields = [
            'node_id',
            'death_time_s',
            'energy_before_j',
            'energy_after_j',
            'cause',
            'event_seq',
        ]
        self._write_rows(deaths_path, death_fields, self.radio.death_events)
        saved_files['node_deaths'] = deaths_path

        reachability_path = out_path / 'reachability_events.csv'
        reachability_fields = [
            'time_s',
            'event_seq',
            'alive_sensors',
            'reachable_sensors',
            'reachability_ratio',
            'state',
            'trigger',
            'death_node_id',
        ]
        self._write_rows(
            reachability_path,
            reachability_fields,
            self.reachability_history,
        )
        saved_files['reachability_events'] = reachability_path

        timeseries_path = out_path / 'timeseries.csv'
        self._write_timeseries_csv(timeseries_path, self._timeseries_for_export())
        saved_files['timeseries'] = timeseries_path

        serviceability_path = out_path / 'serviceability_snapshots.csv'
        self._write_rows(
            serviceability_path,
            SERVICEABILITY_COLUMNS,
            self._serviceability_for_export(),
        )
        saved_files['serviceability_snapshots'] = serviceability_path

        manifest_path = out_path / 'run_manifest.json'
        output_names = [path.name for path in saved_files.values()]
        output_names.append(manifest_path.name)
        manifest = create_run_manifest(
            self.config,
            output_names,
            Path.cwd(),
            run_metadata={
                'export_schema_version': 4,
                'routing_algorithm': self.routing_algorithm,
                'communication_range_m': self.network.communication_range_m,
                'topology_seed': self.config.seed,
                'traffic_seed': self.traffic_seed,
                'requested_duration_s': self.requested_duration_s,
                'actual_duration_s': float(self.env.now),
                'bandwidth_bps': (
                    self.traffic_gen.bandwidth_bps if self.traffic_gen else None
                ),
                'queue_capacity_packets': (
                    self.traffic_gen.queue_capacity if self.traffic_gen else None
                ),
                'alpha_energy': self.alpha_energy,
                'radio_model': {
                    'e_elec_j_bit': self.radio.e_elec,
                    'e_fs_j_bit_m2': self.radio.e_fs,
                    'e_mp_j_bit_m4': self.radio.e_mp,
                    'e_da_j_bit': self.radio.e_da,
                    'd0_m': self.radio.d0,
                },
                'payload_convention': (
                    'payload_size_bytes defaults to packet_size_bytes; '
                    'no protocol overhead is modeled'
                ),
                'time_convention': (
                    'SimPy time; t0=0; metrics cover [0,T); events exactly at '
                    'the run_for stop boundary execute on a later continuation'
                ),
                'lifetime_convention': (
                    'sensor alive-to-dead transitions at energy debit time; '
                    'FND=1st, HND=ceil(N_initial/2), LND=N_initial'
                ),
                'reachability_convention': (
                    'physical graph induced by alive sensors and all sinks; '
                    'network lifetime is the first alive-sensor reachability '
                    'ratio below 0.5 or the first state with no alive sensors; '
                    'the ratio denominator remains the currently alive sensors'
                ),
                'energy_feasibility_convention': (
                    'read-only independent one-packet snapshot using current '
                    'TX/RX energy and MHR/EMHR relay rules; not a guarantee of '
                    'concurrent or future delivery; no idle/sensing energy is modeled'
                ),
                'serviceability_sampling_convention': (
                    'sampled at initialization, every 10 seconds, and observation end; '
                    'energy service lifetime is not an exact event timestamp'
                ),
                'timeseries_snapshot_order': (
                    'initial at t=0; periodic monitor after packet generators '
                    'already scheduled at the same time; final after all events in [0,T)'
                ),
            },
        )
        save_json(manifest, manifest_path)
        saved_files['manifest'] = manifest_path
        return saved_files
