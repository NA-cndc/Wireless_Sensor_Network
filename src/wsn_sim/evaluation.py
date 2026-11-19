from collections.abc import Mapping
from wsn_sim.config import require_number
from wsn_sim.detection import ForwardingDetector

def classification_metrics(population: set[str], attackers: set[str], predicted: set[str]) -> dict:
    truth = attackers & population
    positive = predicted & population
    tp, fp = (len(positive & truth), len(positive - truth))
    fn, tn = (len(truth - positive), len(population - truth - positive))
    unavailable = {}

    def divide(name, numerator, denominator):
        if denominator == 0:
            unavailable[name] = 'zero_denominator'
            return None
        return numerator / denominator
    recall = divide('recall', tp, tp + fn)
    if recall is None:
        unavailable['tpr'] = 'zero_denominator'
    return {'population_size': len(population), 'population_ids': sorted(population), 'TP': tp, 'FP': fp, 'TN': tn, 'FN': fn, 'tpr': recall, 'recall': recall, 'fpr': divide('fpr', fp, fp + tn), 'precision': divide('precision', tp, tp + fp), 'f1': divide('f1', 2 * tp, 2 * tp + fp + fn), 'population_conservation_ok': tp + fp + tn + fn == len(population), 'na_reasons': unavailable}

def security_metrics(sensor_ids, attacker_ids, detector: ForwardingDetector, time_s: float, *, attack_start_time_s: float | Mapping[str, float] | None=None, delay_origin: str='attack_start') -> dict:
    require_number('evaluation_time_s', time_s, minimum=detector.started_at, strict=False)
    sensors, attackers = (set(sensor_ids), set(attacker_ids))
    if not sensors.issubset(detector.states):
        raise ValueError('evaluation population must be observed sensor IDs')
    if not attackers.issubset(sensors):
        raise ValueError('ground truth attackers must be sensors in the evaluation population')
    if delay_origin not in {'attack_start', 'first_transit_rx'}:
        raise ValueError('unknown delay origin')
    starts = detector.started_at if attack_start_time_s is None else attack_start_time_s
    if isinstance(starts, Mapping):
        if set(starts) != attackers:
            raise ValueError('attack start mapping must cover exactly the ground truth attackers')
        origins = dict(starts)
    else:
        origins = dict.fromkeys(attackers, starts)
        require_number('attack_start_time_s', starts, minimum=detector.started_at, strict=False)
    for origin in origins.values():
        require_number('attack_start_time_s', origin, minimum=detector.started_at, strict=False)
        if origin > time_s:
            raise ValueError('attack start must not be after evaluation cutoff')
    if time_s > detector.now:
        detector.advance(time_s)
    predicted = {node for node in sensors if detector.states[node].suspected_at is not None and detector.states[node].suspected_at <= time_s}
    if not detector.retain_history and time_s != detector.now:
        raise ValueError('streaming evaluator supports only the current cutoff')
    if not detector.retain_history and any((origin != detector.started_at for origin in origins.values())):
        raise ValueError('streaming delay origins must be the static simulation attack start')
    observed = {row['relay_id'] for row in detector.windows if row['relay_id'] in sensors and row['status'] == 'valid' and (row['time_s'] <= time_s)}
    if not detector.retain_history:
        observed = {node for node in sensors if detector.states[node].valid_windows > 0}
    unconditional = classification_metrics(sensors, attackers, predicted)
    conditional = classification_metrics(observed, attackers, predicted)
    conditional['population_rule'] = 'at_least_one_valid_closed_cohort_by_cutoff'
    delays = {}
    for node in sorted(attackers):
        state = detector.states[node]
        origin = origins[node]
        if delay_origin == 'first_transit_rx':
            origin = min((row.received_at_s for row in detector.observations.values() if row.relay_id == node and origins[node] <= row.received_at_s <= time_s), default=None) if detector.retain_history else state.first_received_at
        times = {}
        for event, attribute in (('suspected', 'suspected_at'), ('isolated', 'isolated_at')):
            first = getattr(state, attribute)
            candidates = [row['time_s'] for row in detector.events if row['relay_id'] == node and row['event'] == event and (origin is not None) and (origin <= row['time_s'] <= time_s)]
            if first is not None and origin is not None and (origin <= first <= time_s):
                candidates.append(first)
            times[event] = min(candidates, default=None)
        prior = state.suspected_at if origin is not None and state.suspected_at is not None and (state.suspected_at < origin) else None
        detection_reason = None if times['suspected'] is not None else 'no_transit_opportunity' if origin is None else 'no_post_origin_detection' if prior is not None else 'not_detected'
        isolation_reason = None if times['isolated'] is not None else 'no_transit_opportunity' if origin is None else 'not_isolated'
        delays[node] = {'delay_origin_s': origin, 'delay_origin_rule': delay_origin, 'attack_started_at_s': origins[node], 'evaluation_time_s': time_s, 'detection_delay_s': None if times['suspected'] is None else times['suspected'] - origin, 'isolation_delay_s': None if times['isolated'] is None else times['isolated'] - origin, 'detection_censored': times['suspected'] is None, 'isolation_censored': times['isolated'] is None, 'detection_na_reason': detection_reason, 'isolation_na_reason': isolation_reason, 'pre_origin_suspected_at_s': prior, 'at_risk_duration_s': None if origin is None else time_s - origin}
    unavailable = unconditional['na_reasons']
    coverage = len(observed) / len(sensors) if sensors else None
    if coverage is None:
        unavailable['coverage'] = 'zero_denominator'
    return {**unconditional, 'evaluation_scope': 'node', 'evaluation_time_s': time_s, 'cutoff_boundary': 'inclusive', 'evaluation_rule': 'ever_suspected_by_evaluation_time_all_sensors', 'prediction_interval_start_s': detector.started_at, 'sufficiently_observed_nodes': len(observed), 'coverage': coverage, 'conditional_on_observable': conditional, 'attacker_delays': delays, 'delay_origin_s': starts if not isinstance(starts, Mapping) and delay_origin == 'attack_start' else None, 'delay_origin_rule': delay_origin, 'pre_attack_alarm_rule': 'classification_uses_ever_suspected_history_delay_requires_post_origin_alarm'}
