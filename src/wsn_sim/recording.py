from collections import Counter
import csv
import json
from pathlib import Path

class EventJournal(list):

    def __init__(self, callback=None, retain=True):
        super().__init__()
        self.callback = callback
        self.retain = retain
        self.written_count = 0

    def append(self, row):
        self.written_count += 1
        if self.callback is not None:
            self.callback(row)
        if self.retain:
            super().append(row)

class RunRecorder:

    def __init__(self, directory: str | Path, full_trace: bool=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.full_trace = full_trace
        self.energy = Counter()
        self.transitions = Counter()
        self.cohort = Counter()
        self.handles = {}
        self.series_file = None
        self.series_writer = None
        self.max_active_packets = 0
        self.max_live_observations = 0

    def emit(self, name, row):
        if name == 'energy_events':
            self.energy['total'] += row['consumed_j']
            if row['reason'] in {'TX', 'RX', 'radio'}:
                self.energy['radio'] += row['consumed_j']
        elif name == 'detector_events' and row['event'] in {'suspected', 'isolated', 'probation', 'recovered'}:
            self.transitions[row['event']] += 1
        elif name == 'detector_windows' and row['status'] == 'valid':
            self.cohort['observations'] += row['observations']
            self.cohort['forwarded'] += row['forwarded']
            self.cohort['valid_cohorts'] += 1
        if self.full_trace:
            if name not in self.handles:
                self.handles[name] = (self.directory / f'{name}.jsonl').open('x', encoding='utf-8', buffering=1024 * 1024)
            self.handles[name].write(json.dumps(row, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')

    def journal(self, name, callback=None):

        def consume(row):
            if callback is not None:
                callback(row)
            self.emit(name, row)
        return EventJournal(consume, retain=False)

    def snapshot(self, simulation):
        summary = simulation.summary()
        performance, network = (summary['performance'], simulation.network)
        states = list(simulation.detector.states.values()) if simulation.detector is not None else []
        row = {'time_s': summary['time_s'], 'alive_sensors': sum((node.is_alive for node in network.sensors.values())), 'remaining_energy_j': performance['remaining_energy_j'], 'generated': performance['generated'], 'delivered': performance['delivered'], 'dropped': performance['dropped'], 'in_flight': performance['pending_in_flight'], 'received_payload_bits': performance['received_payload_bits'], 'received_wire_bits': performance['received_wire_bits'], 'trust_mean_all_sensors': sum((state.trust for state in states)) / len(states) if states else None, 'cohort_observations_since_sample': self.cohort['observations'], 'cohort_forwarded_since_sample': self.cohort['forwarded'], 'cohort_FR_since_sample': self.cohort['forwarded'] / self.cohort['observations'] if self.cohort['observations'] else None, 'suspected_current': sum((state.suspected for state in states)), 'isolated_current': sum((state.isolated_until is not None for state in states)), 'observable_nodes': sum((state.valid_windows > 0 for state in states)), 'reroute_decisions': performance['reroute_decision_count'], 'route_edges_changed': performance['route_edges_changed'], 'physical_reachable_alive': summary['reachability']['physical_reachable_alive'], 'routing_reachable_alive': summary['reachability']['routing_reachable_alive']}
        if self.series_file is None:
            self.series_file = (self.directory / 'timeseries.csv').open('x', encoding='utf-8', newline='')
            self.series_writer = csv.DictWriter(self.series_file, fieldnames=list(row))
            self.series_writer.writeheader()
        self.series_writer.writerow(row)
        self.series_file.flush()
        self.cohort.clear()
        self.max_active_packets = max(self.max_active_packets, len(simulation.traffic_gen.active_packets))
        if simulation.detector is not None:
            self.max_live_observations = max(self.max_live_observations, len(simulation.detector.observations))
        return summary

    def close(self):
        for handle in self.handles.values():
            handle.close()
        if self.series_file is not None:
            self.series_file.close()

    def metadata(self):
        return {'mode': 'bounded_active_state_streaming', 'full_trace': self.full_trace, 'packet_id_rule': 'unique_sensor_sequence_ids_single_path_terminal_guard_no_MAC_replay', 'detector_history': 'pending_and_unclosed_cohorts_only', 'historical_evaluator_queries': False, 'bulk_unreachable': not self.full_trace, 'max_active_packets_sampled': self.max_active_packets, 'max_live_observations_sampled': self.max_live_observations, 'files': sorted((path.name for path in self.directory.iterdir() if path.is_file()))}
