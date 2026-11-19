from __future__ import annotations
from copy import deepcopy
from math import isfinite
import simpy
from wsn_sim.config import SimulationConfig
from wsn_sim.detection import ForwardingDetector
from wsn_sim.energy import RadioModel
from wsn_sim.metrics import LifetimeTracker, METRIC_SCHEMA, performance_metrics, security_metrics
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.randomness import randomness_metadata
from wsn_sim.recording import RunRecorder
from wsn_sim.traffic import TrafficGenerator

class Simulation:

    def __init__(self, config: SimulationConfig, current_range_m: float | None=None, env: simpy.Environment | None=None, *, network: Network | None=None, recorder: RunRecorder | None=None) -> None:
        if not isinstance(config, SimulationConfig):
            raise TypeError('config must be a SimulationConfig; pass custom topology with network=')
        if network is not None and network.config != config:
            raise ValueError('network and simulation must use the same configuration')
        if network is not None and current_range_m is not None:
            raise ValueError('choose an existing network or current_range_m')
        self.config = config
        self.recorder = recorder
        self.env = env if env is not None else simpy.Environment()
        self.started_at = float(self.env.now)
        self.network = Network(config, current_range_m) if network is None else network
        self.detector = None if config.detector is None else ForwardingDetector(config.detector, self.network.sensors, self.started_at, sink_ids=self.network.sinks, retain_history=recorder is None, observation_sink=self._record_detector_event if recorder else None)
        self.router = RoutingEngine(self.network, self.detector)
        self.router.cache_enabled = recorder is not None
        if recorder is not None:
            for sink in self.network.sinks.values():
                sink.retain_packet_ids = False
        self.radio = RadioModel()
        self.stop_event = self.env.event()
        self.lifetime = LifetimeTracker(self.network, self.router, start_time_s=self.started_at, complete_payload_history=True)
        self.network_events: list[dict] = []
        if recorder is not None:
            self.network_events = recorder.journal('network_events')
            self.lifetime.retain_history = False
            self.lifetime.events = recorder.journal('lifetime_events')
            self.lifetime.reachability_events = recorder.journal('reachability_events')
        self.traffic_gen = TrafficGenerator(self.env, self.network, self.router, self.radio, config, detector=self.detector, on_delivery=self._record_delivery, recorder=recorder)
        self.energy_events = self.traffic_gen.energy_events
        for sensor in self.network.sensors.values():
            sensor.energy_observer = self._energy_changed
            sensor.energy_clock = lambda: float(self.env.now)
        self._observe_network()
        self.traffic_gen.start()
        if self.detector is not None:
            self.env.process(self._monitor_detector())

    def _record_detector_event(self, name, row):
        self.recorder.emit(name, row)
        if self.config.routing_algorithm == 'S_EMHR' and name == 'detector_events' and (row['event'] in {'isolated', 'probation'}):
            node = row['relay_id']
            effective_gain = row['event'] == 'probation' and self.network.sensors[node].can_forward(self.config.energy_threshold_j)
            self.router.invalidate_cache(node, removed=not effective_gain)

    def _record_delivery(self) -> None:
        self.lifetime.record_received(float(self.env.now), self.traffic_gen.delivered_payload_bits)

    def _energy_changed(self, event: dict) -> None:
        self.energy_events.append({**event, 'received_payload_bits_before': self.traffic_gen.delivered_payload_bits})
        threshold = self.config.energy_threshold_j
        if event['became_dead'] or event['before_j'] >= threshold > event['after_j']:
            self.router.invalidate_cache(event['node_id'], removed=True)
            self._observe_network()

    def _observe_network(self) -> None:
        self.lifetime.observe(float(self.env.now), self.traffic_gen.delivered_payload_bits)
        if all((not sensor.is_alive for sensor in self.network.sensors.values())) and (not self.stop_event.triggered):
            self.stop_event.succeed()

    def set_link_state(self, sender_id: str, receiver_id: str, *, available: bool) -> None:
        nodes = self.network.sensors.keys() | self.network.sinks.keys()
        if sender_id not in nodes or receiver_id not in nodes or sender_id == receiver_id:
            raise ValueError('link endpoints must be distinct physical nodes')
        if not isinstance(available, bool):
            raise TypeError('link availability must be boolean')
        if sender_id in self.network.sinks and receiver_id in self.network.sinks:
            raise ValueError('sink-to-sink links are not modeled')
        graph = self.network.graph
        if graph.has_edge(sender_id, receiver_id) == available:
            return
        if available:
            distance = self.network.distance(sender_id, receiver_id)
            if distance > self.network.communication_range_m:
                raise ValueError('link exceeds physical communication range')
            graph.add_edge(sender_id, receiver_id, distance_m=distance)
        else:
            graph.remove_edge(sender_id, receiver_id)
        self.router.invalidate_cache()
        self.network_events.append({'time_s': float(self.env.now), 'event': 'link_state', 'sender_id': sender_id, 'receiver_id': receiver_id, 'available': available})
        self._observe_network()

    def _monitor_detector(self):
        while not self.stop_event.triggered:
            yield self.env.timeout(self.detector.next_transition_time_s - self.env.now)
            self.detector.advance(float(self.env.now))
            self._observe_network()

    def run_for(self, duration_s: float) -> float:
        if not isfinite(duration_s) or duration_s <= 0:
            raise ValueError('duration_s must be finite and greater than zero')
        limit = self.started_at + self.config.max_duration_s
        target = min(float(self.env.now) + duration_s, limit)
        self._observe_network()
        if target > self.env.now and (not self.stop_event.triggered):
            self.env.run(until=self.stop_event | self.env.timeout(target - self.env.now))
            while not self.stop_event.triggered and self.env.peek() == self.env.now:
                self.env.step()
        if self.detector is not None:
            self.detector.advance(float(self.env.now))
        self._observe_network()
        return float(self.env.now)

    def run(self) -> dict:
        remaining = self.started_at + self.config.max_duration_s - self.env.now
        if remaining > 0:
            self.run_for(remaining)
        return self.summary()

    def summary(self) -> dict:
        if self.detector is not None:
            self.detector.advance(float(self.env.now))
        self._observe_network()
        stop_reason = 'LND' if self.stop_event.triggered else 'max_rounds' if self.env.now >= self.started_at + self.config.max_duration_s else 'duration'
        return {'metric_schema': METRIC_SCHEMA, 'config_profile': self.config.config_profile, 'energy_configuration': self.config.energy_configuration, 'time_s': float(self.env.now), 'rounds': self.traffic_gen.rounds, 'stop_reason': stop_reason, 'performance': performance_metrics(self.network, self.traffic_gen, self.env.now - self.started_at), 'lifetime': deepcopy(self.lifetime.milestones), 'lifetime_metadata': {**deepcopy(self.lifetime.metadata), 'observation_end_s': float(self.env.now), 'censoring_reason': stop_reason, 'round_duration_s': self.config.packet_interval_s}, 'reachability': dict(self.lifetime.reachability), 'security': None if self.detector is None else security_metrics(self.network.sensors, self.traffic_gen.attack.attacker_ids, self.detector, float(self.env.now), attack_start_time_s=self.started_at), 'detector': None if self.detector is None else self.detector.summary(), 'attack': self.traffic_gen.attack.to_dict(), 'stream_seeds': self.config.stream_seeds, 'randomness': randomness_metadata(), 'detector_status': 'NEEDS_CALIBRATION' if self.detector is None else self.config.detector.calibration_status}
