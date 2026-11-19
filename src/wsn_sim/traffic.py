from __future__ import annotations
from collections.abc import Callable
import simpy
from wsn_sim.attacks import SelectiveForwarding
from wsn_sim.config import SimulationConfig
from wsn_sim.detection import ForwardingDetector
from wsn_sim.energy import RadioModel
from wsn_sim.models import Packet, Sensor, Sink
from wsn_sim.metrics import PacketAccumulator
from wsn_sim.network import Network
from wsn_sim.randomness import event_occurs
from wsn_sim.routing import RoutingEngine

class TrafficGenerator:

    def __init__(self, env: simpy.Environment, network: Network, router: RoutingEngine, radio: RadioModel, config: SimulationConfig, *, detector: ForwardingDetector | None=None, on_state_change: Callable[[], None] | None=None, on_delivery: Callable[[], None] | None=None, recorder=None) -> None:
        self.env = env
        self.network = network
        self.router = router
        self.radio = radio
        self.config = config
        self.detector = detector
        self.recorder = recorder
        self.online_metrics = PacketAccumulator(retain_completed=False) if recorder is not None else None
        self.active_packets = {}
        self._validated_routes = {}
        self._reroute_sequence = 0
        self.on_state_change = on_state_change
        self.on_delivery = on_delivery
        self.initial_energy_at_start_j = {node: sensor.energy_j for node, sensor in network.sensors.items()}
        self.energy_events: list[dict] = []
        self.attack = SelectiveForwarding(config, network.sensors, network=network)
        self.channel_seed = config.stream_seeds['channel_loss']
        self.generated_packets: list[Packet] = []
        self.delivered_packets: list[Packet] = []
        self.dropped_packets: list[Packet] = []
        self.events: list[dict] = []
        self.reroute_decisions: list[dict] = []
        self.delivered_payload_bits = 0
        self.rounds = 0
        self.started = False
        if recorder is not None:
            self.events = recorder.journal('packet_events', self.online_metrics.consume)
            self.energy_events = recorder.journal('energy_events')
            self.reroute_decisions = recorder.journal('reroute_decisions')

    @property
    def reroutes(self) -> list[dict]:
        return [row for row in self.reroute_decisions if row['outcome'] == 'rerouted']

    @property
    def delivered_latencies(self) -> list[float]:
        return [packet.latency_s for packet in self.delivered_packets]

    def start(self) -> None:
        if self.started:
            raise RuntimeError('traffic has already started')
        self.started = True
        self.env.process(self._round_loop())

    def _round_loop(self):
        for round_index in range(1, self.config.max_rounds + 1):
            yield self.env.timeout(self.config.packet_interval_s)
            alive = sorted((node for node, sensor in self.network.sensors.items() if sensor.is_alive))
            if not alive:
                return
            self.rounds = round_index
            if self.recorder is not None and (not self.recorder.full_trace):
                reachable = set(self.router.reachable_sensor_ids(float(self.env.now)))
                unreachable = [node for node in alive if node not in reachable]
                for node in unreachable:
                    self.network.sensors[node].generated_packets += 1
                    self.network.sensors[node].dropped_packets += 1
                self.online_metrics.bulk_unreachable(len(unreachable))
                self.recorder.emit('bulk_unreachable', {'time_s': float(self.env.now), 'source_count': len(unreachable), 'generated_and_dropped': len(unreachable)})
                alive = [node for node in alive if node in reachable]
            for sensor_id in alive:
                self.generate_packet(sensor_id)

    def generate_packet(self, sensor_id: str) -> Packet | None:
        sensor = self.network.sensors[sensor_id]
        if not sensor.is_alive:
            return None
        sensor.generated_packets += 1
        packet = Packet(f'{sensor_id}_p{sensor.generated_packets}', sensor_id, float(self.env.now), self.config.packet_size_bytes, wire_size_bytes=self.config.transmission_size_bytes)
        if self.recorder is None:
            self.generated_packets.append(packet)
        else:
            self.active_packets[packet.packet_id] = packet
        self._log(packet, 'created', payload_size_bytes=packet.size_bytes, wire_size_bytes=packet.wire_size_bytes)
        route = self.router.find_route(sensor_id, time_s=float(self.env.now))
        if route is None:
            self._drop(packet, 'unreachable', no_route=True)
        else:
            packet.assign_route(route)
            if self.recorder is not None:
                self._validated_routes[packet.packet_id] = self.router.validation_epoch
            self.env.process(self._transmit_packet(packet))
        return packet

    def _log(self, packet: Packet, event: str, node_id: str | None=None, **details) -> None:
        self.events.append({'time_s': float(self.env.now), 'packet_id': packet.packet_id, 'source_id': packet.source_id, 'node_id': node_id or packet.current_node_id, 'event': event, 'status': packet.status.value, 'reason': None, **details})

    def _drop(self, packet: Packet, reason: str, *, no_route: bool=False, node_id: str | None=None, **details) -> None:
        if packet.mark_dropped(reason, no_route):
            if self.recorder is None:
                self.dropped_packets.append(packet)
            holder = self.network.sensors.get(node_id or packet.current_node_id)
            if holder is not None:
                holder.dropped_packets += 1
            self._log(packet, 'dropped', node_id, reason=reason, **details)
            self.active_packets.pop(packet.packet_id, None)
            self._validated_routes.pop(packet.packet_id, None)

    def _spend(self, sensor: Sensor, amount_j: float, stage: str, packet_id: str) -> bool:
        was_alive = sensor.is_alive
        enough = self.radio.spend(sensor, amount_j, float(self.env.now), reason=stage, packet_id=packet_id)
        if was_alive != sensor.is_alive and self.on_state_change is not None:
            self.on_state_change()
        return enough

    def _reroute(self, packet: Packet, issues: list[dict]) -> bool:
        previous = list(packet.planned_route)
        options = {'packet_source_id': packet.source_id, 'forbidden': set(packet.actual_path[:-1]), 'time_s': float(self.env.now)}
        route = self.router.find_route(packet.current_node_id, target_sink=previous[-1], **options)
        if route is None:
            route = self.router.find_route(packet.current_node_id, **options)
        old_edges = set(zip(previous, previous[1:]))
        added, removed = ([], [])
        if route is not None:
            packet.assign_route(route)
            new_edges = set(zip(packet.planned_route, packet.planned_route[1:]))
            added = [list(edge) for edge in sorted(new_edges - old_edges)]
            removed = [list(edge) for edge in sorted(old_edges - new_edges)]
        primary = issues[0]
        self._reroute_sequence += 1
        record = {'decision_id': f'reroute_{self._reroute_sequence}', 'time_s': float(self.env.now), 'packet_id': packet.packet_id, 'node_id': packet.current_node_id, 'reason': primary['reason'], 'reason_category': primary['reason_category'], 'issues': issues, 'trigger_nodes': sorted({row['node_id'] for row in issues if row.get('node_id') is not None}), 'route_before': previous, 'route_after': list(packet.planned_route) if route is not None else None, 'sink_before': previous[-1], 'sink_after': route[-1] if route is not None else None, 'sink_changed': route is not None and previous[-1] != route[-1], 'added_edges': added, 'removed_edges': removed, 'added_edge_count': len(added), 'removed_edge_count': len(removed), 'outcome': 'rerouted' if route is not None else 'unreachable'}
        self.reroute_decisions.append(record)
        event = 'rerouted' if route is not None else 'reroute_failed'
        self._log(packet, event, **{key: value for key, value in record.items() if key not in {'time_s', 'packet_id', 'node_id'}})
        if route is None:
            self._drop(packet, 'unreachable', no_route=True)
            return False
        return True

    def _transmit_packet(self, packet: Packet):
        bits = packet.wire_size_bytes * 8
        delay_s = bits / self.config.bandwidth_bps
        while not packet.is_terminal:
            remaining = packet.planned_route[packet.current_hop_index:]
            sender = self.network.sensors[packet.current_node_id]
            if not sender.is_alive:
                self._drop(packet, 'energy_depletion')
                return
            if self.recorder is not None and self.detector is not None:
                self.detector.advance(float(self.env.now))
            version = self.router.validation_epoch
            issues = [] if self.recorder is not None and self._validated_routes.get(packet.packet_id) == version else self.router.route_issues(remaining, packet.source_id, float(self.env.now))
            if issues:
                if not self._reroute(packet, issues):
                    return
                remaining = packet.planned_route[packet.current_hop_index:]
            if self.recorder is not None:
                self._validated_routes[packet.packet_id] = self.router.validation_epoch
            receiver_id = remaining[1]
            receiver = self.network.sensors.get(receiver_id) or self.network.sinks[receiver_id]
            hop = {'sender_id': sender.node_id, 'receiver_id': receiver_id, 'attempt_index': 0}
            tx_j = self.radio.compute_tx_energy(bits, self.network.distance(sender.node_id, receiver_id))
            tx_budget_j = sender.energy_j
            if not self._spend(sender, tx_j, 'TX', packet.packet_id):
                self._drop(packet, 'energy_depletion', energy_stage='TX', energy_j=tx_budget_j, **hop)
                return
            self._log(packet, 'tx', next_node_id=receiver_id, energy_j=tx_j, **hop)
            if sender.node_id != packet.source_id:
                sender.forwarded_packets += 1
            if self.detector is not None:
                self.detector.observe_forwarded(sender.node_id, packet.packet_id, float(self.env.now), source_id=packet.source_id)
            yield self.env.timeout(delay_s)
            if not self.network.graph.has_edge(sender.node_id, receiver_id):
                self._drop(packet, 'unreachable', energy_j=0.0, **hop)
                return
            if event_occurs(self.channel_seed, self.config.channel_loss_probability, packet.packet_id, sender.node_id, receiver_id, hop['attempt_index']):
                self._drop(packet, 'natural_link_loss', energy_j=0.0, **hop)
                return
            if isinstance(receiver, Sensor):
                rx_j = self.radio.compute_rx_energy(bits)
                rx_budget_j = receiver.energy_j
                if not self._spend(receiver, rx_j, 'RX', packet.packet_id):
                    self._drop(packet, 'energy_depletion', node_id=receiver_id, energy_stage='RX', energy_j=rx_budget_j, **hop)
                    return
            packet.advance_to(receiver_id)
            self._log(packet, 'rx', energy_j=0.0 if isinstance(receiver, Sink) else rx_j, **hop)
            if self.detector is not None:
                self.detector.observe_received(receiver_id, packet.packet_id, packet.source_id, float(self.env.now))
            if isinstance(receiver, Sink):
                if receiver.receive(packet, float(self.env.now)):
                    if self.recorder is None:
                        self.delivered_packets.append(packet)
                    self.delivered_payload_bits += packet.size_bytes * 8
                    self._log(packet, 'delivered', actual_hops=packet.actual_hop_count, latency_s=packet.latency_s)
                    self.active_packets.pop(packet.packet_id, None)
                    self._validated_routes.pop(packet.packet_id, None)
                    if self.on_delivery is not None:
                        self.on_delivery()
                return
            receiver.received_packets += 1
            if self.attack.drops(receiver_id, packet.packet_id, packet.source_id, attempt_index=hop['attempt_index']):
                self._drop(packet, 'selective_forwarding', energy_j=0.0, **hop)
                return
