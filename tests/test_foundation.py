from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import subprocess
import sys
import pytest
import simpy
from wsn_sim.config import DEFAULT_CONFIG_PATH, SimulationConfig
from wsn_sim.models import Packet, PacketStatus, Sensor
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_manifest, save_simulation

def test_plan_default_alias_and_legacy_energy_are_explicitly_separated(project_root):
    plan = SimulationConfig.from_json(project_root / 'configs/plan.json')
    default = SimulationConfig.from_json(project_root / 'configs/default.json')
    legacy = SimulationConfig.from_json(project_root / 'configs/legacy/energy_3j.json')
    assert DEFAULT_CONFIG_PATH == project_root / 'configs/plan.json'
    assert default == SimulationConfig.from_json(project_root / 'configs/experiment_10000s.json')
    assert default.max_duration_s == 10000
    assert plan.max_duration_s == 100000
    assert plan.config_profile == 'PLAN'
    assert plan.energy_configuration == {'initial_energy_j': 5, 'energy_threshold_ratio': 0.2, 'energy_threshold_j': 1}
    assert legacy.config_profile == 'LEGACY_ENERGY_REGRESSION'
    assert legacy.initial_energy_j == 3
    assert legacy.energy_threshold_j == 0.5
    assert plan.energy_configuration != legacy.energy_configuration
    assert SimulationConfig.from_dict(legacy.to_dict()) == legacy

def test_missing_profile_in_old_flat_mapping_is_custom_not_plan(config):
    data = config.to_dict()
    del data['config_profile']
    assert SimulationConfig.from_dict(data).config_profile == 'CUSTOM'

def test_config_inheritance_resolves_relative_paths_and_serializes_flat(project_root, tmp_path):
    base = tmp_path / 'base.json'
    base.write_text((project_root / 'configs/plan.json').read_text(encoding='utf-8'), encoding='utf-8')
    nested = tmp_path / 'nested'
    nested.mkdir()
    child = nested / 'child.json'
    child.write_text(json.dumps({'extends': '../base.json', 'initial_energy_j': 10, 'config_profile': 'CUSTOM'}), encoding='utf-8')
    config = SimulationConfig.from_json(child)
    assert config.initial_energy_j == 10
    assert config.energy_threshold_j == 2
    assert 'extends' not in config.to_dict()
    assert SimulationConfig.from_dict(config.to_dict()) == config

def test_config_inheritance_rejects_cycles(tmp_path):
    first, second = (tmp_path / 'first.json', tmp_path / 'second.json')
    first.write_text('{"extends":"second.json"}', encoding='utf-8')
    second.write_text('{"extends":"first.json"}', encoding='utf-8')
    with pytest.raises(ValueError, match='cycle'):
        SimulationConfig.from_json(first)

@pytest.mark.parametrize('data', [[], {'extends': None}, {'extends': ''}, {'extends': 42}])
def test_config_inheritance_rejects_invalid_documents(tmp_path, data):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(TypeError):
        SimulationConfig.from_json(path)

def test_config_inheritance_still_rejects_unknown_declared_fields(project_root, tmp_path):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps({'extends': str(project_root / 'configs/plan.json'), 'unknown_field': 1}), encoding='utf-8')
    with pytest.raises(ValueError, match='unknown configuration fields'):
        SimulationConfig.from_json(path)

@pytest.mark.parametrize('profile', ['legacy', 'OPTIMAL', ''])
def test_config_profile_rejects_unknown_labels(config, profile):
    with pytest.raises(ValueError, match='config_profile'):
        replace(config, config_profile=profile)

def test_config_and_slotted_models_cannot_gain_undeclared_fields(config):
    with pytest.raises(FrozenInstanceError):
        config.initial_energy_j = 3
    for model in (Sensor('s', 0, 0, 5), Packet('p', 's', 0, 128)):
        with pytest.raises(AttributeError):
            model.undeclared_field = True
        assert not hasattr(model, '__dict__')
    assert not hasattr(config, '__dict__')

def test_simulation_config_api_rejects_old_positional_network_form(network_factory):
    network = network_factory({'s': (0, 0)}, [('s', 'k')])
    with pytest.raises(TypeError, match='config must be a SimulationConfig'):
        Simulation(network, simpy.Environment())
    with pytest.raises(ValueError, match='existing network or current_range_m'):
        Simulation(network.config, current_range_m=300, network=network)
    with pytest.raises(ValueError, match='same configuration'):
        Simulation(replace(network.config, seed=99), network=network)

def test_live_low_energy_source_can_deliver_own_packet(network_factory):
    network = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')])
    network.sensors['s'].consume_energy(4.5, 0)
    simulation = Simulation(network.config, network=network)
    packet = simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    assert packet.status is PacketStatus.DELIVERED
    assert packet.planned_route == packet.actual_path == ['s', 'a', 'k']
    assert packet.planned_hop_count == packet.actual_hop_count == 2
    assert packet.route == packet.planned_route

def test_rx_budget_failure_does_not_increment_actual_hops_or_sink_count(network_factory):
    network = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], routing_algorithm='MHR', sinks={'k': (20, 0)})
    simulation = Simulation(network.config, network=network)
    half_rx = simulation.radio.compute_rx_energy(1024) / 2
    network.sensors['a'].consume_energy(5 - half_rx, 0)
    packet = simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    assert packet.status is PacketStatus.DROPPED
    assert packet.drop_reason == 'energy_depletion'
    assert packet.planned_hop_count == 2
    assert packet.actual_hop_count == 0
    assert packet.actual_path == ['s']
    assert network.sensors['a'].energy_j == 0
    assert network.sensors['a'].died_at == pytest.approx(1024 / 250000)
    assert network.sinks['k'].received_packet_count == 0
    assert simulation.summary()['performance']['conservation_ok']

def test_manifest_and_summary_keep_profile_and_battery_configuration(config, project_root):
    for profile, energy in (('PLAN', 5), ('LEGACY_ENERGY_REGRESSION', 3)):
        cfg = replace(config, config_profile=profile, initial_energy_j=energy)
        manifest = create_run_manifest(cfg, [], project_root)
        summary = Simulation(cfg).summary()
        assert manifest['config_profile'] == summary['config_profile'] == profile
        assert manifest['energy_configuration'] == summary['energy_configuration'] == cfg.energy_configuration
        assert manifest['configuration']['initial_energy_j'] == energy

def test_saved_packets_distinguish_planned_actual_and_wire_payload(network_factory, tmp_path, project_root):
    import pandas as pd
    network = network_factory({'s': (0, 0)}, [('s', 'k')], wire_size_bytes=160)
    simulation = Simulation(network.config, network=network)
    simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    save_simulation(simulation, tmp_path, project_root)
    row = pd.read_csv(tmp_path / 'packets.csv').iloc[0]
    assert row['planned_route'] == row['actual_path'] == 's -> k'
    assert row['planned_hops'] == row['actual_hops'] == 1
    assert row['payload_size_bytes'] == 128
    assert row['wire_size_bytes'] == 160

def test_foundation_check_writes_measured_reachability_and_known_graph(project_root, tmp_path):
    result = subprocess.run([sys.executable, '-m', 'analysis.check_foundation', '--seeds', '42', '--output', str(tmp_path)], cwd=project_root, check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report['stage'] == 1
    assert report['checks_passed']
    assert report['known_graph']['matches_expected']
    assert len(report['reachability']['rows']) == 3
    assert report['reachability']['selected_main_range_m'] is None
    assert report['legacy']['performance_run'] is False
    for row in report['reachability']['rows']:
        assert row['reachable_ratio'] == row['routable_sensors'] / 450
        assert row['fully_reachable'] == (row['routable_sensors'] == 450)
    directory = Path(report['output_directory'])
    assert (directory / 'foundation_check.json').exists()
    manifest = json.loads((directory / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['config_profile'] == 'CUSTOM'
    assert all((Path(path).exists() for path in manifest['generated_files']))

def test_foundation_check_rejects_repeated_seeds(project_root, tmp_path):
    result = subprocess.run([sys.executable, '-m', 'analysis.check_foundation', '--seeds', '42', '42', '--output', str(tmp_path)], cwd=project_root, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'unique non-negative' in result.stderr
