from dataclasses import replace
import pytest
from wsn_sim.config import DetectorConfig
from wsn_sim.recording import RunRecorder
from wsn_sim.routing import RoutingEngine
from wsn_sim.simulation import Simulation

@pytest.mark.parametrize('algorithm', ['MHR', 'EMHR', 'S_EMHR'])
@pytest.mark.parametrize('full_trace', [False, True])
def test_streaming_matches_full_state_metrics_and_keyed_attack_events(config, tmp_path, algorithm, full_trace):
    detector = DetectorConfig(0.5, 5, 0.1, 1, 0.8, 2, 1, 10)
    cfg = replace(config, config_profile='TEST_ONLY', num_sensors=18, num_sinks=2, area_width_m=100, area_height_m=100, communication_range_m=35, max_rounds=24, seed=7021, routing_algorithm=algorithm, attacker_ratio=0.25, p_drop=0.5, channel_loss_probability=0.05, detector=detector)
    full = Simulation(cfg)
    full.run()
    recorder = RunRecorder(tmp_path / 'stream', full_trace)
    stream = Simulation(cfg, recorder=recorder)
    stream.run()
    expected, actual = (full.summary(), stream.summary())
    for key, value in expected['performance'].items():
        if isinstance(value, float):
            assert actual['performance'][key] == pytest.approx(value, abs=1e-10)
        else:
            assert actual['performance'][key] == value, key
    assert actual['lifetime'] == expected['lifetime']
    assert actual['security'] == expected['security']
    assert [node.generated_packets for node in stream.network.sensors.values()] == [node.generated_packets for node in full.network.sensors.values()]
    assert stream.traffic_gen.attack.attacker_ids == full.traffic_gen.attack.attacker_ids
    assert len(stream.traffic_gen.generated_packets) == len(stream.traffic_gen.events) == 0
    assert len(stream.detector.windows) == len(stream.detector.events) == 0
    assert not any((sink.received_packet_ids for sink in stream.network.sinks.values()))
    recorder.close()

def test_compact_run_keeps_memory_bounded_over_ten_thousand_rounds(network_factory, detector_config, tmp_path):
    network = network_factory({'s': (0, 0)}, [], max_rounds=10000, detector=detector_config)
    recorder = RunRecorder(tmp_path)
    simulation = Simulation(network.config, network=network, recorder=recorder)
    simulation.run()
    performance = simulation.summary()['performance']
    assert performance['generated'] == performance['dropped'] == 10000
    assert performance['pending_in_flight'] == 0
    assert performance['conservation_ok'] and performance['energy_conservation_ok']
    assert simulation.network.sensors['s'].generated_packets == 10000
    assert not simulation.traffic_gen.active_packets
    assert not simulation.traffic_gen.online_metrics.packets
    assert not simulation.detector.observations
    assert len(simulation.lifetime.receipt_history) <= 1
    assert len(simulation.energy_events) == len(simulation.detector.windows) == 0
    assert simulation.summary()['stop_reason'] == 'max_rounds'
    recorder.close()

def test_route_cache_does_not_freeze_energy_ties(network_factory):
    network = network_factory({'s': (0, 0), 'a': (50, 10), 'b': (50, -10)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')])
    router = RoutingEngine(network)
    router.cache_enabled = True
    network.sensors['b'].consume_energy(1, 0)
    assert router.get_emhr_route('s') == ['s', 'a', 'k']
    network.sensors['a'].consume_energy(2, 0)
    assert router.get_emhr_route('s') == ['s', 'b', 'k']
    assert router.cache_hits == 0

def test_streaming_historical_queries_are_rejected_instead_of_invented(network_factory, detector_config, tmp_path):
    from wsn_sim.metrics import security_metrics
    network = network_factory({'s': (0, 0)}, [('s', 'k')], detector=detector_config)
    recorder = RunRecorder(tmp_path)
    simulation = Simulation(network.config, network=network, recorder=recorder)
    simulation.run_for(10.1)
    with pytest.raises(ValueError, match='current cutoff'):
        security_metrics(network.sensors, [], simulation.detector, 5)
    recorder.close()

def test_detector_without_avoidance_does_not_invalidate_emhr_cache(network_factory, detector_config, tmp_path):
    network = network_factory({'s': (0, 0), 'a': (50, 0)}, [('s', 'a'), ('a', 'k')], routing_algorithm='EMHR', detector=detector_config)
    recorder = RunRecorder(tmp_path)
    simulation = Simulation(network.config, network=network, recorder=recorder)
    router = simulation.router
    assert router.get_emhr_route('s') == ['s', 'a', 'k']
    epoch = router.validation_epoch
    simulation.detector.states['a'].isolated_until = 100
    simulation.detector.routing_epoch += 1
    simulation._record_detector_event('detector_events', {'event': 'isolated', 'relay_id': 'a'})
    hits = router.cache_hits
    assert router.validation_epoch == epoch
    assert router.get_emhr_route('s') == ['s', 'a', 'k']
    assert router.cache_hits == hits + 1
    assert router.find_route('s', 'S_EMHR', time_s=0) is None
    recorder.close()

def test_selective_cache_removal_keeps_unaffected_paths_and_invalidates_on_gain(network_factory):
    network = network_factory({'s': (0, 0), 'a': (50, 0), 'v': (0, 50), 'b': (50, 50)}, [('s', 'a'), ('a', 'k'), ('v', 'b'), ('b', 'k')])
    router = RoutingEngine(network)
    router.cache_enabled = True
    assert router.get_emhr_route('s') == ['s', 'a', 'k']
    assert router.get_emhr_route('v') == ['v', 'b', 'k']
    network.sensors['a'].consume_energy(4.5, 0)
    router.invalidate_cache('a', removed=True)
    hits = router.cache_hits
    assert router.get_emhr_route('v') == ['v', 'b', 'k']
    assert router.cache_hits == hits + 1
    assert router.get_emhr_route('s') is None
    network.sensors['b'].consume_energy(4.5, 0)
    router.invalidate_cache('b', removed=True)
    hits = router.cache_hits
    assert router.get_emhr_route('s') is None and router.cache_hits == hits + 1
    network.sensors['a'].energy_j = 5
    router.invalidate_cache()
    assert router.get_emhr_route('s') == ['s', 'a', 'k']
