from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter
import traceback
from uuid import uuid4
from wsn_sim.calibration import json_digest, source_fingerprint
from wsn_sim.config import SimulationConfig
from wsn_sim.evaluation import classification_metrics
from wsn_sim.recording import RunRecorder
from wsn_sim.topology import topology_record
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_manifest, save_json

def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)

def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def peak_memory_bytes():
    if os.name == 'nt':
        from ctypes import wintypes

        class Memory(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
        value = Memory()
        value.cb = ctypes.sizeof(value)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        api = ctypes.windll.psapi.GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
        if not api(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(value), value.cb):
            raise OSError('peak working set unavailable')
        return value.peak
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)

@contextmanager
def coordinator_lock(directory):
    handle = (directory / 'runner.lock').open('a+b')
    if handle.tell() == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('another coordinator owns this batch')
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == 'nt':
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

def disabled_security(simulation):
    result = classification_metrics(set(simulation.network.sensors), set(simulation.traffic_gen.attack.attacker_ids), set())
    result.update({'evaluation_scope': 'node', 'evaluation_time_s': float(simulation.env.now), 'evaluation_rule': 'detector_disabled_predict_none_all_sensors', 'coverage': 0, 'sufficiently_observed_nodes': 0, 'detector_enabled': False, 'attacker_delays': {node: {'delay_origin_s': simulation.started_at, 'detection_delay_s': None, 'isolation_delay_s': None, 'detection_censored': True, 'isolation_censored': True, 'detection_na_reason': 'detector_disabled', 'isolation_na_reason': 'detector_disabled', 'at_risk_duration_s': float(simulation.env.now) - simulation.started_at} for node in sorted(simulation.traffic_gen.attack.attacker_ids)}})
    return result

def execute_worker(spec, directory, root):
    started, recorder = (perf_counter(), None)
    try:
        if source_fingerprint(root)['sha256'] != spec['source_sha256']:
            raise ValueError('source changed before worker start')
        body = dict(spec)
        expected_id = body.pop('run_id')
        body.pop('timeout_s', None)
        if json_digest(body)[:24] != expected_id:
            raise ValueError('worker configuration hash mismatch')
        config = SimulationConfig.from_dict(spec['configuration'])
        horizon = spec.get('pilot_duration_s', config.max_duration_s)
        if spec['scope'] == 'EVALUATION_MAX_ROUNDS_10000' and (horizon != 100000 or config.max_rounds != 10000):
            raise ValueError('official evaluation must keep 10000 rounds of 10 seconds')
        recorder = RunRecorder(directory, spec['full_trace'])
        simulation = Simulation(config, recorder=recorder)
        topology = topology_record(simulation.network)
        summary = recorder.snapshot(simulation)
        while simulation.env.now < horizon and (not simulation.stop_event.triggered):
            simulation.run_for(min(spec['sample_interval_s'], horizon - simulation.env.now))
            summary = recorder.snapshot(simulation)
            if perf_counter() - started > spec.get('timeout_s', 3600):
                raise TimeoutError('worker wall-clock budget exceeded')
        if summary['security'] is None:
            summary['security'] = disabled_security(simulation)
        summary['log_end_s'] = recorder.log_end_s
        if not summary['performance']['conservation_ok'] or not summary['performance']['energy_conservation_ok']:
            raise RuntimeError('packet/energy conservation failed')
        recorder.close()
        save_json(summary, directory / 'summary.json')
        save_json({node: {'energy_j': sensor.energy_j, 'alive': sensor.is_alive, 'died_at': sensor.died_at, 'generated': sensor.generated_packets, 'received_transit': sensor.received_packets, 'forwarded': sensor.forwarded_packets, 'dropped': sensor.dropped_packets} for node, sensor in simulation.network.sensors.items()}, directory / 'final_sensor_states.json')
        save_json({'events': simulation.lifetime.milestones, 'metadata': summary['lifetime_metadata']}, directory / 'lifetime.json')
        recording = recorder.metadata()
        recording.update({'active_packets_at_end': len(simulation.traffic_gen.active_packets), 'live_observations_at_end': len(simulation.detector.observations) if simulation.detector else 0, 'route_cache_hits': simulation.router.cache_hits, 'cache_policy': 'unique_primary_paths_selective_monotone_removal_global_gain_invalidation'})
        save_json(recording, directory / 'recording.json')
        save_json(topology, directory / 'topology.json')
        files = [path for path in directory.iterdir() if path.is_file() and path.name not in {'stdout.log', 'stderr.log', 'spec.json', 'complete.json'}]
        manifest = create_run_manifest(config, files, root)
        manifest.update({
            'run_id': spec['run_id'], 'case': spec['case'], 'scope': spec['scope'],
            'pairing_hash': spec['pairing_hash'], 'source_sha256': spec['source_sha256'],
            'topology_hash': topology['topology_hash'], 'topology_seed': topology['topology_seed'],
            'actual_num_sensors': topology['actual_num_sensors'],
            'attack': summary['attack'], 'frozen_detector': spec['freeze'], 'status': 'COMPLETE',
            'actual_duration_s': summary['time_s'], 'log_end_s': recorder.log_end_s,
            'requested_horizon_s': horizon, 'wall_clock_s': perf_counter() - started,
            'peak_working_set_bytes': peak_memory_bytes(),
            'output_bytes_before_manifest': sum(path.stat().st_size for path in files),
            'command': sys.argv, 'recording': recording,
        })
        save_json(manifest, directory / 'run_manifest.json')
        files.append(directory / 'run_manifest.json')
        complete = {'run_id': spec['run_id'], 'status': 'COMPLETE', 'source_sha256': spec['source_sha256'], 'files': {path.name: file_hash(path) for path in files}}
        atomic_json(directory / 'complete.json', complete)
        return complete
    except BaseException as error:
        if recorder is not None:
            recorder.close()
        atomic_json(directory / 'failure.json', {'run_id': spec.get('run_id'), 'status': 'TIMEOUT' if isinstance(error, TimeoutError) else 'FAILED', 'error': f'{type(error).__name__}: {error}', 'traceback': traceback.format_exc(), 'wall_clock_s': perf_counter() - started})
        raise

def valid_completion(directory, spec):
    try:
        complete = json.loads((directory / 'complete.json').read_text(encoding='utf-8'))
        required = {'summary.json', 'run_manifest.json', 'timeseries.csv', 'recording.json', 'topology.json', 'final_sensor_states.json', 'lifetime.json'}
        if not required.issubset(complete['files']):
            return False
        manifest = json.loads((directory / 'run_manifest.json').read_text(encoding='utf-8'))
        if json_digest(manifest['configuration']) != json_digest(spec['configuration']):
            return False
        return complete['run_id'] == spec['run_id'] and complete['source_sha256'] == spec['source_sha256'] and (complete['status'] == 'COMPLETE') and all(((directory / name).is_file() and file_hash(directory / name) == digest for name, digest in complete['files'].items()))
    except (OSError, ValueError, KeyError):
        return False
