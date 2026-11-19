import json
import os
import subprocess
import sys
from wsn_sim.randomness import event_occurs
from wsn_sim.simulation import Simulation

def test_event_keyed_randomness_does_not_depend_on_draw_order(config):
    seed = config.stream_seeds['channel_loss']
    keys = [(f'p{index}', 's', 'a') for index in range(20)]
    forward = {key: event_occurs(seed, 0.5, *key) for key in keys}
    reverse = {key: event_occurs(seed, 0.5, *key) for key in reversed(keys)}
    assert forward == reverse
    assert not event_occurs(seed, 0, 'p', 's', 'a')
    assert event_occurs(seed, 1, 'p', 's', 'a')
    assert set(config.stream_seeds) == {'topology', 'traffic', 'routing', 'attacker_selection', 'attack_decision', 'channel_loss'}
    assert len(set(config.stream_seeds.values())) == 6

def test_simulations_reproduce_packets_attacks_and_energy(network_factory):
    settings = {'attacker_ratio': 0.5, 'p_drop': 0.5, 'channel_loss_probability': 0.05}

    def run():
        net = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], **settings)
        simulation = Simulation(net.config, network=net)
        simulation.run_for(31)
        return (simulation.summary(), simulation.traffic_gen.events)
    assert run() == run()

def test_results_reproduce_across_processes_and_python_hash_seeds(project_root):
    code = "from dataclasses import replace; from pathlib import Path; import json; from wsn_sim import Simulation, SimulationConfig; c=replace(SimulationConfig.from_json(Path('configs/default.json')),num_sensors=24,num_sinks=2,area_width_m=300,area_height_m=300,communication_range_m=80,attacker_ratio=0.25,p_drop=0.5,channel_loss_probability=0.05); s=Simulation(c); s.run_for(21); print(json.dumps({'coordinates':s.network.coordinates(),'summary':s.summary()},sort_keys=True))"
    outputs = []
    for seed in ('1', '932'):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run([sys.executable, '-c', code], cwd=project_root, env=env, check=True, capture_output=True, text=True)
        outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1]
    assert outputs[0]['summary']['performance']['conservation_ok']
