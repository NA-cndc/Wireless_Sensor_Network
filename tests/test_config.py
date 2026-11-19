from dataclasses import replace
from pathlib import Path
import pytest
from wsn_sim.config import SimulationConfig

def test_load_default_configuration(project_root: Path) -> None:
    config = SimulationConfig.from_json(project_root / 'configs' / 'default.json')
    assert (config.area_width_m, config.area_height_m) == (3000, 3000)
    assert config.num_sensors == 450
    assert config.num_sinks == 7
    assert config.communication_ranges_m == (250, 300, 350)
    assert config.seed == 42
    assert config.initial_energy_j == 5
    assert config.energy_threshold_j == 1
    assert config.communication_range_m == 300
    assert config.max_rounds == 1000
    assert config.max_duration_s == 10000
    assert config.transmission_size_bytes == config.packet_size_bytes == 128
    assert config.detector is None

@pytest.mark.parametrize(('field', 'invalid_value'), [('area_width_m', 0), ('area_height_m', -1), ('num_sensors', 0), ('num_sinks', -1), ('initial_energy_j', 0), ('packet_size_bytes', -128), ('packet_interval_s', 0)])
def test_reject_non_positive_configuration_values(config: SimulationConfig, field: str, invalid_value: int) -> None:
    with pytest.raises(ValueError):
        replace(config, **{field: invalid_value})

def test_reject_missing_required_range(config: SimulationConfig) -> None:
    with pytest.raises(ValueError, match='250, 300, and 350'):
        replace(config, communication_ranges_m=(250, 300))

def test_reject_non_integer_seed(config: SimulationConfig) -> None:
    with pytest.raises(TypeError, match='seed'):
        replace(config, seed=42.5)

@pytest.mark.parametrize(('energy', 'ratio', 'threshold'), [(5, 0.1, 0.5), (5, 0.2, 1), (5, 0.3, 1.5), (10, 0.2, 2)])
def test_threshold_is_derived_from_config(config, energy, ratio, threshold):
    assert replace(config, initial_energy_j=energy, energy_threshold_ratio=ratio).energy_threshold_j == threshold

def test_config_round_trip_keeps_nested_detector_and_explicit_attackers(config, detector_config):
    cfg = replace(config, detector=detector_config, attacker_ids=('sensor_000',), routing_algorithm='S_EMHR')
    assert SimulationConfig.from_dict(cfg.to_dict()) == cfg
    assert cfg.stream_seeds == SimulationConfig.from_dict(cfg.to_dict()).stream_seeds

@pytest.mark.parametrize(('name', 'value'), [('initial_energy_j', float('nan')), ('bandwidth_bps', float('inf')), ('p_drop', 1.1), ('attacker_ratio', -0.1), ('channel_loss_probability', 2), ('max_rounds', 0), ('wire_size_bytes', 64), ('energy_threshold_ratio', 1.1), ('routing_algorithm', 'unknown'), ('attacker_ids', ('a', 'a'))])
def test_reject_invalid_extended_config(config, name, value):
    with pytest.raises(ValueError):
        replace(config, **{name: value})

@pytest.mark.parametrize(('name', 'value'), [('beta_trust', 0), ('beta_trust', 1), ('window_size_s', 0), ('forwarding_timeout_s', -1), ('min_observations', 0), ('trust_threshold', 1.1), ('consecutive_bad_windows', 0), ('initial_trust', -1), ('isolation_duration_s', 0), ('calibration_status', 'OPTIMAL')])
def test_detector_config_requires_valid_explicit_parameters(detector_config, name, value):
    with pytest.raises(ValueError):
        replace(detector_config, **{name: value})

def test_semhr_cannot_start_with_implicit_uncalibrated_parameters(config):
    with pytest.raises(ValueError, match='calibration'):
        replace(config, routing_algorithm='S_EMHR')

def test_config_mapping_preserves_missing_field_validation(config):
    data = config.to_dict()
    del data['seed']
    with pytest.raises(ValueError, match='missing configuration fields: seed'):
        SimulationConfig.from_dict(data)
    with pytest.raises(ValueError, match='unknown configuration fields'):
        SimulationConfig.from_dict({**config.to_dict(), 'misspelled_parameter': 1})
