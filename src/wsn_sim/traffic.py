"""Periodic data traffic and queued, energy-accounted radio transmissions."""

from collections import Counter
from collections.abc import Callable
from hashlib import blake2b
from random import Random

import simpy

from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.models.packet import Packet
from wsn_sim.models.sensor import Sensor
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine


class TrafficGenerator:
    def __init__(
        self, env: simpy.Environment, network: Network, router: RoutingEngine,
        radio: RadioModel, config: SimulationConfig, routing_algo: str = "EMHR",
        on_death: Callable[[], None] | None = None,
    ) -> None:
        self.env = env
        self.network = network
        self.router = router
        self.radio = radio
        self.config = config
        self.routing_algo = routing_algo
        self.on_death = on_death
        self.generated_packets = []
        self.delivered_packets = []
        self.dropped_packets = []
        self.delivered_latencies = []
        self.drop_counts: Counter[str] = Counter()
        self.energy_j: Counter[str] = Counter()
        self.tx_attempts = 0
        self.rounds = 0
        self.delivered_bytes = 0
        self.total_latency_s = 0.0
        self.pending: dict[str, Packet] = {}
        self.transmitting: set[str] = set()
        self.cutoff_state: dict[str, str] = {}
        self.cutoff_s = float("inf")
        self._beacon_rng = Random(config.effective_traffic_seed)
        self._channel_key = blake2b(str(config.effective_channel_seed).encode()).digest()
        self._route_graph = network.graph
        self._emhr_routes: dict[str, list[str] | None] = {}
        self.route_changes = 0
        self.tx_queues = {node_id: simpy.Resource(env, capacity=1) for node_id in network.sensors}

    def start(self) -> None:
        self.env.process(self._traffic_loop())
        for sensor_id in self.network.routable_sensor_ids():
            self.env.process(self._beacon_loop(sensor_id))

    def _consume(self, sensor: Sensor, amount_j: float, category: str) -> None:
        before = sensor.energy_j
        remaining = sensor.consume_energy(amount_j)
        self.energy_j[category] += before - remaining

    def _beacon_loop(self, sensor_id: str):
        beacon_size_bits = 24 * 8
        beacon_interval_s = 50.0
        sensor = self.network.sensors[sensor_id]
        yield self.env.timeout(self._beacon_rng.uniform(0.1, beacon_interval_s))
        while sensor.is_alive:
            tx_energy = self.radio.compute_tx_energy(beacon_size_bits, self.network.communication_range_m)
            self._consume(sensor, tx_energy, "beacon_tx_j")
            deaths = not sensor.is_alive
            if sensor.is_alive:
                rx_energy = self.radio.compute_rx_energy(beacon_size_bits)
                for neighbor_id in self.network.neighbors(sensor_id):
                    neighbor = self.network.sensors.get(neighbor_id)
                    if neighbor is not None and neighbor.is_alive:
                        self._consume(neighbor, rx_energy, "beacon_rx_j")
                        deaths |= not neighbor.is_alive
            if deaths and self.on_death is not None:
                self.on_death()
            yield self.env.timeout(beacon_interval_s)

    def _source_route(self, source_id: str) -> list[str] | None:
        if self.routing_algo != "EMHR":
            return self.router.get_route(source_id, self.routing_algo)
        graph = self.network.graph
        if graph is not self._route_graph:
            self._route_graph = graph
            self._emhr_routes.clear()
        if source_id in self._emhr_routes:
            previous = self._emhr_routes[source_id]
            if previous is None or self._valid_emhr_suffix(previous):
                return previous
        else:
            previous = None
        route = self.router.get_emhr_route(source_id)
        self.route_changes += previous is not None and route is not None and route != previous
        self._emhr_routes[source_id] = route
        return route

    def _valid_emhr_suffix(self, route: list[str]) -> bool:
        sensors = self.network.sensors
        threshold = self.router.relay_threshold_j
        return all(sensors[node].can_forward(threshold) for node in route[1:-1]) and all(
            self.network.graph.has_edge(left, right) for left, right in zip(route, route[1:])
        )

    def _traffic_loop(self):
        while True:
            yield self.env.timeout(self.config.packet_interval_s)
            self.rounds += 1
            for sensor in self.network.sensors.values():
                if not sensor.is_alive:
                    continue
                sensor.generated_packets += 1
                packet = Packet(
                    packet_id=f"{sensor.node_id}_p{self.rounds}",
                    source_id=sensor.node_id,
                    created_at=float(self.env.now),
                    size_bytes=self.config.packet_size_bytes,
                )
                self.generated_packets.append(packet)
                route = self._source_route(sensor.node_id)
                if route is None:
                    self._drop(packet, "unreachable")
                    continue
                packet.assign_route(route)
                self.pending[packet.packet_id] = packet
                self.env.process(self._transmit_packet(packet))

    def _drop(self, packet: Packet, reason: str) -> None:
        packet.mark_dropped(reason, no_route=reason == "unreachable")
        self.pending.pop(packet.packet_id, None)
        self.network.sensors[packet.source_id].dropped_packets += 1
        self.dropped_packets.append(packet)
        self.drop_counts[reason] += 1

    def close_pending(self, reason: str) -> None:
        for packet in list(self.pending.values()):
            self.cutoff_state[packet.packet_id] = (
                "transmitting" if packet.packet_id in self.transmitting else "queued"
            )
            self._drop(packet, reason)

    def _channel_lost(self, packet: Packet, sender_id: str, receiver_id: str) -> bool:
        probability = self.config.channel_loss_probability
        if probability == 0:
            return False
        key = f"{packet.packet_id}/{sender_id}/{receiver_id}".encode()
        draw = int.from_bytes(blake2b(key, key=self._channel_key, digest_size=8).digest(), "big")
        return draw < probability * (1 << 64)

    def _transmit_packet(self, packet: Packet):
        bits = packet.size_bytes * 8
        duration_s = bits / 250_000.0
        sensors = self.network.sensors
        sinks = self.network.sinks
        while packet.current_hop_index < packet.hop_count:
            hop = packet.current_hop_index
            sender_id = packet.route[hop]
            sender = sensors[sender_id]
            with self.tx_queues[sender_id].request() as request:
                yield request
                if self.env.now >= self.cutoff_s:
                    return
                receiver_id = packet.route[hop + 1]
                if not sender.is_alive:
                    self._drop(packet, "energy_depletion")
                    return
                if self.routing_algo == "EMHR":
                    if hop > 0 and not sender.can_forward(self.router.relay_threshold_j):
                        self._drop(packet, "unreachable")
                        return
                    if not self._valid_emhr_suffix(packet.route[hop:]):
                        suffix = self.router.get_emhr_route(sender_id, excluded=set(packet.route[:hop]))
                        if suffix is None:
                            self._drop(packet, "unreachable")
                            return
                        packet.route[hop:] = suffix
                        receiver_id = suffix[1]
                        self.route_changes += 1
                edge = self.network.graph.get_edge_data(sender_id, receiver_id)
                if edge is None:
                    self._drop(packet, "unreachable")
                    return
                receiver = sensors.get(receiver_id)
                if receiver is not None and not receiver.is_alive:
                    self._drop(packet, "energy_depletion")
                    return

                tx_energy = self.radio.compute_tx_energy(bits, edge["distance_m"])
                if sender.energy_j < tx_energy:
                    self._consume(sender, sender.energy_j, "data_tx_depletion_j")
                    self._drop(packet, "energy_depletion")
                    if self.on_death is not None:
                        self.on_death()
                    return
                self._consume(sender, tx_energy, "data_tx_j")
                packet.tx_attempts += 1
                self.tx_attempts += 1
                if hop > 0:
                    sender.forwarded_packets += 1
                self.transmitting.add(packet.packet_id)
                if not sender.is_alive and self.on_death is not None:
                    self.on_death()
                yield self.env.timeout(duration_s)
                self.transmitting.remove(packet.packet_id)

                if self._channel_lost(packet, sender_id, receiver_id):
                    self._drop(packet, "natural_link_loss")
                    return
                if receiver is not None:
                    if not receiver.is_alive:
                        self._drop(packet, "energy_depletion")
                        return
                    rx_energy = self.radio.compute_rx_energy(bits)
                    enough = receiver.energy_j >= rx_energy
                    self._consume(receiver, rx_energy, "data_rx_j")
                    if enough:
                        receiver.received_packets += 1
                    if not receiver.is_alive and self.on_death is not None:
                        self.on_death()
                    if not enough:
                        self._drop(packet, "energy_depletion")
                        return
                packet.current_hop_index += 1

        if sinks[packet.route[-1]].receive(packet, float(self.env.now)):
            self.pending.pop(packet.packet_id)
            self.delivered_packets.append(packet)
            self.delivered_latencies.append(packet.latency_s)
            self.total_latency_s += packet.latency_s
            self.delivered_bytes += packet.size_bytes
