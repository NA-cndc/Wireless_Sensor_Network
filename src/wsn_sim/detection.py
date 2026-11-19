from __future__ import annotations
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from heapq import heappop, heappush
from math import isfinite
from wsn_sim.config import DetectorConfig, require_number
from wsn_sim.recording import EventJournal
ISOLATION_EXPIRY = 0
FORWARDING_DEADLINE = 1

@dataclass(slots=True)
class ForwardingObservation:
    relay_id: str
    packet_id: str
    source_id: str
    received_at_s: float
    deadline_s: float
    cohort_index: int
    outcome: str = 'pending'
    resolved_at_s: float | None = None

@dataclass(slots=True)
class RelayState:
    trust: float
    received_transit: int = 0
    forwarded: int = 0
    failed_timeout: int = 0
    pending: int = 0
    excluded_rx: int = 0
    excluded_tx: int = 0
    valid_windows: int = 0
    bad_windows: int = 0
    suspected: bool = False
    isolated_until: float | None = None
    probation: bool = False
    probation_started_at_s: float | None = None
    first_received_at: float | None = None
    suspected_at: float | None = None
    isolated_at: float | None = None

    @property
    def received(self) -> int:
        return self.received_transit

    @property
    def failed(self) -> int:
        return self.failed_timeout

    @property
    def excluded(self) -> int:
        return self.excluded_rx + self.excluded_tx

    @property
    def conservation_ok(self) -> bool:
        return self.received_transit == self.forwarded + self.failed_timeout + self.pending

class ForwardingDetector:

    def __init__(self, config: DetectorConfig, sensor_ids, start_time_s: float=0.0, *, sink_ids=(), retain_history: bool=True, observation_sink=None) -> None:
        if not isinstance(config, DetectorConfig):
            raise TypeError('detector requires only a DetectorConfig')
        require_number('start_time_s', start_time_s, strict=False)
        if isinstance(sensor_ids, str) or isinstance(sink_ids, str):
            raise TypeError('node catalogs must be collections of IDs')
        sensor_ids, sink_ids = (tuple(sensor_ids), tuple(sink_ids))
        self._validate_ids(*sensor_ids, *sink_ids)
        self.config = config
        self.retain_history = retain_history
        self.routing_epoch = 0
        self.states = {node: RelayState(config.initial_trust) for node in sorted(sensor_ids)}
        self.sink_ids = frozenset(sink_ids)
        if self.sink_ids.intersection(self.states):
            raise ValueError('sensor and sink observation catalogs must be disjoint')
        self.observations: dict[tuple[str, str], ForwardingObservation] = {}
        self._cohorts: dict[int, dict[str, list[ForwardingObservation]]] = {}
        self._scheduled: list[tuple[float, int, str, str]] = []
        self._input_counts = Counter({'rx': 0, 'tx': 0})
        self._excluded_counts: Counter[tuple[str, str]] = Counter()
        self.windows: list[dict] = []
        self.events: list[dict] = []
        if not retain_history:
            self.events = EventJournal(lambda row: observation_sink('detector_events', row) if observation_sink else None, retain=False)
            self.windows = EventJournal(lambda row: observation_sink('detector_windows', row) if observation_sink else None, retain=False)
        self.started_at = float(start_time_s)
        self.now = float(start_time_s)
        self._origin = Decimal(str(start_time_s))
        self._window_size = Decimal(str(config.window_size_s))
        self._window_index = 0
        require_number('first_window_end_s', self.next_window)
        if self.next_window <= self.started_at:
            raise ValueError('window_size_s must advance the simulation clock')

    @property
    def next_window(self) -> float:
        return self._window_boundary(self._window_index + 1)

    @property
    def next_transition_time_s(self) -> float:
        return min([self.next_window, *(state.isolated_until for state in self.states.values() if state.isolated_until is not None)])

    @property
    def pending(self) -> dict[tuple[str, str], float]:
        return {key: row.deadline_s for key, row in self.observations.items() if row.outcome == 'pending'}

    @property
    def exclusions(self) -> list[dict]:
        return [row for row in self.events if row['event'] == 'excluded']

    @staticmethod
    def model_metadata() -> dict:
        return {'version': 'ideal_observer_deadline_cohorts_v1', 'observation_model': 'ideal_synchronous_simpy_events', 'success_event': 'relay_tx_started_with_sufficient_energy', 'next_hop_ack_required': False, 'cohort_rule': 'observation_deadline_in_half_open_window', 'trust_update_at': 'cohort_window_end', 'timeout_rule': 'forward_observation_must_precede_deadline_strictly', 'insufficient_data_rule': 'preserve_trust_and_bad_valid_window_streak', 'backdated_event_rule': 'reject_non_monotonic_observer_time', 'probation_rule': 'N_min_fresh_transit_RX_after_expiry_required_for_recovery_or_reisolation', 'overhearing_or_ack_modeled': False}

    def _window_boundary(self, index: int) -> float:
        return float(self._origin + index * self._window_size)

    @staticmethod
    def _later(time_s: float, duration_s: float) -> float:
        later = float(Decimal(str(time_s)) + Decimal(str(duration_s)))
        if not isfinite(later) or later <= time_s:
            raise ValueError('time interval must advance a finite simulation clock')
        return later

    @staticmethod
    def _validate_ids(*values: str) -> None:
        if any((not isinstance(value, str) for value in values)):
            raise TypeError('observation IDs must be strings')
        if any((not value for value in values)):
            raise ValueError('observation IDs must not be empty')

    def _exclude(self, kind: str, relay_id: str, packet_id: str, time_s: float, reason: str, source_id=None) -> None:
        self._excluded_counts[kind, reason] += 1
        state = self.states.get(relay_id)
        if state is not None:
            if kind == 'rx':
                state.excluded_rx += 1
            else:
                state.excluded_tx += 1
        self.events.append({'time_s': time_s, 'relay_id': relay_id, 'packet_id': packet_id, 'source_id': source_id, 'event': 'excluded', 'observation_kind': kind, 'reason': reason})

    def _ineligible_reason(self, relay_id: str, source_id: str | None) -> str | None:
        if relay_id in self.sink_ids:
            return 'sink'
        if relay_id not in self.states:
            return 'unknown_node'
        if relay_id == source_id:
            return 'own_packet'
        return None

    def observe_received(self, relay_id: str, packet_id: str, source_id: str, time_s: float) -> None:
        self._validate_ids(relay_id, packet_id, source_id)
        self.advance(time_s)
        reason = self._ineligible_reason(relay_id, source_id)
        key = (relay_id, packet_id)
        if reason is None and key in self.observations:
            reason = 'duplicate_received'
        if reason is None:
            deadline = self._later(time_s, self.config.forwarding_timeout_s)
            cohort = int((Decimal(str(deadline)) - self._origin) // self._window_size)
        self._input_counts['rx'] += 1
        if reason is not None:
            self._exclude('rx', relay_id, packet_id, time_s, reason, source_id)
            return
        observation = ForwardingObservation(relay_id, packet_id, source_id, time_s, deadline, cohort)
        self.observations[key] = observation
        self._cohorts.setdefault(cohort, {}).setdefault(relay_id, []).append(observation)
        heappush(self._scheduled, (deadline, FORWARDING_DEADLINE, relay_id, packet_id))
        state = self.states[relay_id]
        state.received_transit += 1
        state.pending += 1
        if state.first_received_at is None:
            state.first_received_at = time_s
        self.events.append({'time_s': time_s, 'relay_id': relay_id, 'packet_id': packet_id, 'source_id': source_id, 'event': 'received_transit', 'outcome': 'pending', 'deadline_s': deadline, 'cohort_index': cohort, 'reason': None})

    def observe_forwarded(self, relay_id: str, packet_id: str, time_s: float, *, source_id: str | None=None) -> None:
        self._validate_ids(relay_id, packet_id)
        if source_id is not None:
            self._validate_ids(source_id)
        self.advance(time_s)
        self._input_counts['tx'] += 1
        reason = self._ineligible_reason(relay_id, source_id)
        observation = self.observations.get((relay_id, packet_id))
        if reason is None:
            if observation is None:
                reason = 'unmatched_forwarded'
            elif source_id is not None and source_id != observation.source_id:
                reason = 'source_mismatch'
            elif observation.outcome == 'forwarded':
                reason = 'duplicate_forwarded'
            elif observation.outcome == 'failed_timeout':
                reason = 'forwarded_after_timeout'
        if reason is not None:
            self._exclude('tx', relay_id, packet_id, time_s, reason, source_id)
            return
        self._resolve(observation, 'forwarded', time_s)

    def _resolve(self, observation: ForwardingObservation, outcome: str, time_s: float) -> None:
        if observation.outcome != 'pending':
            raise RuntimeError('observation has already resolved')
        observation.outcome = outcome
        observation.resolved_at_s = time_s
        state = self.states[observation.relay_id]
        state.pending -= 1
        if outcome == 'forwarded':
            state.forwarded += 1
        else:
            state.failed_timeout += 1
        self.events.append({'time_s': time_s, 'relay_id': observation.relay_id, 'packet_id': observation.packet_id, 'source_id': observation.source_id, 'event': 'forwarded' if outcome == 'forwarded' else 'timeout', 'outcome': outcome, 'deadline_s': observation.deadline_s, 'cohort_index': observation.cohort_index, 'reason': 'relay_tx_observed' if outcome == 'forwarded' else 'forwarding_not_observed_before_deadline'})

    def _state_event(self, node: str, event: str, reason: str, time_s: float, **context) -> None:
        state = self.states[node]
        if event in {'isolated', 'probation'}:
            self.routing_epoch += 1
        self.events.append({'time_s': time_s, 'relay_id': node, 'packet_id': None, 'event': event, 'reason': reason, 'trust': state.trust, 'forwarding_ratio': None, 'observations': 0, 'bad_windows': state.bad_windows, 'suspected': state.suspected, 'isolated_until': state.isolated_until, 'probation': state.probation, 'trust_threshold': self.config.trust_threshold, 'min_observations': self.config.min_observations, 'required_bad_windows': self.config.consecutive_bad_windows, **context})

    def _expire(self, time_s: float) -> None:
        while self._scheduled:
            when, priority, node, packet_id = self._scheduled[0]
            if when > time_s:
                break
            heappop(self._scheduled)
            if priority == FORWARDING_DEADLINE:
                observation = self.observations[node, packet_id]
                if observation.outcome == 'pending':
                    self._resolve(observation, 'failed_timeout', when)
            else:
                state = self.states[node]
                if state.isolated_until == when:
                    state.isolated_until = None
                    state.probation = True
                    state.probation_started_at_s = when
                    state.bad_windows = 0
                    self._state_event(node, 'probation', 'isolation_elapsed_requires_new_observations', when)

    def _close_window(self, time_s: float) -> None:
        window_start = self._window_boundary(self._window_index)
        records = self._cohorts.pop(self._window_index, {})
        for node, state in self.states.items():
            cohort = records.get(node, [])
            if not self.retain_history and (not cohort):
                continue
            if any((row.outcome == 'pending' or row.deadline_s >= time_s for row in cohort)):
                raise RuntimeError('cohort was closed before its observations matured')
            count = len(cohort)
            forwarded = sum((row.outcome == 'forwarded' for row in cohort))
            failed = count - forwarded
            ratio = forwarded / max(count, 1) if count else None
            before = state.trust
            valid = count >= self.config.min_observations
            fresh = sum((row.received_at_s >= state.probation_started_at_s for row in cohort)) if state.probation else count
            streak_eligible = not state.probation or fresh >= self.config.min_observations
            context = {'recovery_observations': fresh, 'streak_eligible': streak_eligible, 'forwarding_ratio': ratio, 'observations': count, 'cohort_index': self._window_index, 'window_start_s': window_start, 'window_end_s': time_s}
            if valid:
                state.valid_windows += 1
                state.trust = self.config.beta_trust * before + (1 - self.config.beta_trust) * ratio
                bad = state.trust < self.config.trust_threshold
                if not bad:
                    state.bad_windows = 0
                elif streak_eligible:
                    state.bad_windows += 1
                if bad and (not state.suspected):
                    state.suspected = True
                    if state.suspected_at is None:
                        state.suspected_at = time_s
                    self._state_event(node, 'suspected', 'trust_below_threshold_with_sufficient_samples', time_s, **context)
                if not bad:
                    state.suspected = False
                    if state.probation and streak_eligible:
                        state.probation = False
                        state.probation_started_at_s = None
                        self._state_event(node, 'recovered', 'fresh_transit_cohort_trust_at_threshold', time_s, **context)
                if state.bad_windows >= self.config.consecutive_bad_windows and state.isolated_until is None:
                    state.isolated_until = self._later(time_s, self.config.isolation_duration_s)
                    state.probation = False
                    state.probation_started_at_s = None
                    if state.isolated_at is None:
                        state.isolated_at = time_s
                    heappush(self._scheduled, (state.isolated_until, ISOLATION_EXPIRY, node, ''))
                    self._state_event(node, 'isolated', 'consecutive_bad_valid_windows', time_s, **context)
            self.windows.append({'time_s': time_s, 'relay_id': node, **context, 'received_transit': count, 'forwarded': forwarded, 'failed_timeout': failed, 'pending': 0, 'received_transit_total': state.received_transit, 'pending_total': state.pending, 'trust_before': before, 'trust': state.trust, 'status': 'valid' if valid else 'insufficient_data', 'reason': None if valid else 'no_matured_observations' if count == 0 else 'below_min_observations', 'bad_windows': state.bad_windows, 'suspected': state.suspected, 'isolated_until': state.isolated_until, 'probation': state.probation, 'cohort_conservation_ok': count == forwarded + failed, 'counter_conservation_ok': state.conservation_ok})
        if not self.retain_history:
            for rows in records.values():
                for row in rows:
                    self.observations.pop((row.relay_id, row.packet_id))

    def advance(self, time_s: float) -> None:
        require_number('time_s', time_s, strict=False)
        if time_s < self.now:
            raise ValueError('detector time must be monotonic')
        if time_s == self.now:
            return
        while self.next_window <= time_s:
            boundary = self.next_window
            self._expire(boundary)
            self._close_window(boundary)
            self._window_index += 1
        self._expire(time_s)
        self.now = float(time_s)

    def is_isolated(self, node_id: str, time_s: float) -> bool:
        self.advance(time_s)
        state = self.states.get(node_id)
        return state is not None and state.isolated_until is not None

    def observation_records(self) -> list[dict]:
        return [{**asdict(row), 'matured': row.deadline_s <= self.now, 'cohort_closed': row.cohort_index < self._window_index, 'cohort_start_s': self._window_boundary(row.cohort_index), 'cohort_end_s': self._window_boundary(row.cohort_index + 1)} for _, row in sorted(self.observations.items())]

    def summary(self) -> dict:
        received = sum((state.received_transit for state in self.states.values()))
        forwarded = sum((state.forwarded for state in self.states.values()))
        failed = sum((state.failed_timeout for state in self.states.values()))
        pending = sum((state.pending for state in self.states.values()))
        excluded_rx = sum((count for (kind, _), count in self._excluded_counts.items() if kind == 'rx'))
        excluded_tx = sum((count for (kind, _), count in self._excluded_counts.items() if kind == 'tx'))
        awaiting = [row for nodes in self._cohorts.values() for rows in nodes.values() for row in rows]
        return {'time_s': self.now, 'model': self.model_metadata(), 'parameters': asdict(self.config), 'received_transit': received, 'forwarded': forwarded, 'failed_timeout': failed, 'pending': pending, 'excluded': excluded_rx + excluded_tx, 'excluded_rx': excluded_rx, 'excluded_tx': excluded_tx, 'input_counts': dict(self._input_counts), 'excluded_by_reason': {f'{kind}:{reason}': count for (kind, reason), count in sorted(self._excluded_counts.items())}, 'closed_cohort_observations': received - len(awaiting), 'observations_awaiting_cohort': len(awaiting), 'known_outcomes_awaiting_cohort': sum((row.outcome != 'pending' for row in awaiting)), 'conservation_ok': received == forwarded + failed + pending and all((state.conservation_ok for state in self.states.values())), 'input_conservation_ok': self._input_counts['rx'] == received + excluded_rx and self._input_counts['tx'] == forwarded + excluded_tx, 'relays': {node: {**asdict(state), 'excluded': state.excluded, 'conservation_ok': state.conservation_ok} for node, state in self.states.items()}}

def benign_calibration_profile(windows: list[dict]) -> dict:
    valid = [row for row in windows if row['status'] == 'valid']
    return {'calibration_status': 'NEEDS_CALIBRATION', 'valid_windows': len(valid), 'minimum_trust': min((row['trust'] for row in valid), default=None), 'forwarding_ratios': [row['forwarding_ratio'] for row in valid], 'trust_samples': [row['trust'] for row in valid], 'observer_model': ForwardingDetector.model_metadata(), 'insufficient_windows': sum((row['status'] == 'insufficient_data' for row in windows))}
