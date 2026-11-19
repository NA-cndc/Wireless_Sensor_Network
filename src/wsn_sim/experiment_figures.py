from collections import defaultdict
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from wsn_sim.experiment_execution import file_hash
COLORS = {'MHR': '#64748b', 'EMHR': '#0f766e', 'MHR_SF': '#c2410c', 'EMHR_SF': '#a16207', 'SF2': '#2563eb', 'SF3': '#7c3aed'}

def draw_figures(plan, records, aggregates, directory, demo_directory=None):
    plt.rcParams.update({'font.size': 10, 'axes.grid': True, 'grid.alpha': 0.22, 'savefig.dpi': 180})
    manifest = []
    center = [row for row in aggregates if (row['rho'] == 0 or (row['rho'] == 0.05 and row['p_drop'] == 0.5)) and row['placement'] == 'random']
    scenarios = list(COLORS)
    config = plan['base_configuration']
    subtitle = f"R={config['communication_range_m']:g} m; channel={config['channel_loss_probability']:g}; E0={config['initial_energy_j']:g} J; rho=5%, p_drop=0.5 for attack scenarios"

    def save(fig, name, data, sources, note):
        data_path = directory / f'{name}_data.csv'
        pd.DataFrame(data).to_csv(data_path, index=False, encoding='utf-8')
        fig.tight_layout()
        fig.savefig(directory / f'{name}.png', bbox_inches='tight')
        fig.savefig(directory / f'{name}.svg', bbox_inches='tight')
        plt.close(fig)
        manifest.append({'figure': name + '.png', 'vector': name + '.svg', 'script': 'scripts/report_experiments.py', 'data_csv': str(data_path), 'data_sha256': file_hash(data_path), 'sources': [{'path': str(path), 'sha256': file_hash(path)} for path in sources], 'configuration': config, 'seeds': plan['seeds'], 'note': note})

    def bars(name, metric_labels, columns=3, selected=center):
        fig, axes = plt.subplots(int(np.ceil(len(metric_labels) / columns)), columns, figsize=(13, 3.5 * np.ceil(len(metric_labels) / columns)), squeeze=False)
        used = []
        for axis, (metric, label) in zip(axes.flat, metric_labels):
            for index, scenario in enumerate(scenarios):
                group = [row for row in selected if row['metric'] == metric and row['scenario'] == scenario and (row['mean'] is not None)]
                if not group:
                    axis.text(index, 0, 'NA', ha='center', va='bottom', color='#64748b')
                    continue
                row = group[0]
                used.append(row)
                axis.bar(index, row['mean'], color=COLORS[scenario], alpha=0.88, width=0.65)
                if row['n_used'] > 1 and row['ci95_low'] is not None:
                    axis.errorbar(index, row['mean'], yerr=[[row['mean'] - row['ci95_low']], [row['ci95_high'] - row['mean']]], color='#172033', capsize=3, fmt='none')
                axis.annotate(f"n={row['n_used']}", (index, row['mean']), textcoords='offset points', xytext=(0, 7), ha='center', fontsize=8)
            axis.set_xticks(range(len(scenarios)), scenarios, rotation=30, ha='right')
            axis.set_title(label)
        for axis in list(axes.flat)[len(metric_labels):]:
            axis.axis('off')
        fig.suptitle(subtitle + '\nMean per seed; Student-t 95% CI only when n>=2; NA and actual n retained', y=1.02, fontsize=11)
        save(fig, name, used, [directory / 'aggregate.csv'], 'Missing/unfinished configurations are not filled with zero; intervals are pointwise across seeds.')
    bars('performance', [('pdr', 'PDR [fraction]'), ('energy_per_payload_bit_j', 'Energy / received payload [J/bit]'), ('mean_latency_s', 'Delivered e2e delay [s]'), ('mean_actual_hops', 'Delivered actual hops [count]'), ('throughput_bps', 'Throughput [wire bit/s]'), ('goodput_bps', 'Goodput [payload bit/s]')])
    bars('security', [('tpr', 'TPR / recall [fraction]'), ('fpr', 'FPR [fraction]'), ('precision', 'Precision [fraction]'), ('f1', 'F1 [fraction]'), ('coverage', 'Observable node coverage [fraction]'), ('detection_capped_delay_s', 'Detection delay capped at common tau [s]')])
    bars('lifetime_and_received_data', [(name + '_restricted_s', name + ' restricted lifetime [s]') for name in ('FND', 'HND', 'LND')] + [(name + '_payload_bits', name + ' payload before observed milestone [bit]') for name in ('FND', 'HND', 'LND')])
    bars('logical_overhead', [('reroute_decision_count', 'Route decisions [count]'), ('route_edges_changed', 'Changed directed edges [count]'), ('isolation_events', 'Isolation decisions [count]')])
    fig, axes = plt.subplots(3, 3, figsize=(14, 10), sharex=True)
    used = []
    for column, probability in enumerate((0.25, 0.5, 0.75)):
        for row_index, (metric, label) in enumerate((('pdr', 'PDR [fraction]'), ('throughput_bps', 'Throughput [bit/s]'), ('goodput_bps', 'Goodput [payload bit/s]'))):
            axis = axes[row_index, column]
            plotted = False
            for scenario in ('MHR_SF', 'EMHR_SF', 'SF2', 'SF3'):
                group = sorted([row for row in aggregates if row['scenario'] == scenario and row['p_drop'] == probability and (row['placement'] == 'random') and (row['metric'] == metric) and (row['mean'] is not None)], key=lambda row: row['rho'])
                if not group:
                    continue
                plotted = True
                used.extend(group)
                x, y = ([100 * row['rho'] for row in group], [row['mean'] for row in group])
                axis.plot(x, y, 'o-', label=scenario, color=COLORS[scenario])
                for px, py, item in zip(x, y, group):
                    if item['n_used'] > 1:
                        axis.errorbar(px, py, yerr=[[py - item['ci95_low']], [item['ci95_high'] - py]], color=COLORS[scenario], capsize=3)
            if not plotted:
                axis.text(0.5, 0.5, 'PENDING', transform=axis.transAxes, ha='center')
            axis.set_title(f'p_drop={probability:g}')
            axis.set_ylabel(label)
            axis.set_xlabel('Attacker ratio [%]')
    if axes[0, 0].get_legend_handles_labels()[0]:
        axes[0, 0].legend(fontsize=8)
    fig.suptitle(f"R={config['communication_range_m']:g} m; channel={config['channel_loss_probability']:g}; random placement", y=1.01)
    save(fig, 'loss_grid', used, [directory / 'aggregate.csv'], 'Actual configurations only; no interpolated missing rho/p_drop results.')
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    curves, sources = ([], [])
    horizon = config['max_rounds'] * config['packet_interval_s']
    interval = plan['jobs'][0]['sample_interval_s']
    grid = np.unique(np.r_[np.arange(0, horizon, interval), horizon])
    for scenario in scenarios:
        selected = [record for record in records if record['job']['case']['scenario'] == scenario and (record['job']['case']['rho'] == 0 or (record['job']['case']['rho'] == 0.05 and record['job']['case']['p_drop'] == 0.5)) and (record['job']['case']['placement'] == 'random')]
        if not selected:
            continue
        matrices = defaultdict(list)
        for record in selected:
            path = record['directory'] / 'timeseries.csv'
            sources.append(path)
            frame = pd.read_csv(path)
            index = np.maximum(0, np.searchsorted(frame['time_s'].to_numpy(), grid, side='right') - 1)
            for field in ('alive_sensors', 'remaining_energy_j'):
                matrices[field].append(frame[field].to_numpy()[index])
        for axis, field in zip(axes, ('alive_sensors', 'remaining_energy_j')):
            matrix = np.array(matrices[field])
            average = matrix.mean(axis=0)
            low = high = None
            if len(matrix) > 1:
                half = stats.t.ppf(0.975, len(matrix) - 1) * matrix.std(axis=0, ddof=1) / np.sqrt(len(matrix))
                low, high = (average - half, average + half)
                axis.fill_between(grid / 3600, low, high, color=COLORS[scenario], alpha=0.12)
            axis.plot(grid / 3600, average, label=f'{scenario} (n={len(matrix)})', color=COLORS[scenario])
            curves.extend(({'scenario': scenario, 'field': field, 'time_s': time, 'mean': value, 'ci95_low': None if low is None else low[index], 'ci95_high': None if high is None else high[index], 'n': len(matrix)} for index, (time, value) in enumerate(zip(grid, average))))
    axes[0].set_ylabel('Alive sensors [count]')
    axes[1].set_ylabel('Remaining sensor energy [J]')
    for axis in axes:
        axis.set_xlabel('Simulation time [h]')
        axis.legend(fontsize=8)
    fig.suptitle(subtitle)
    save(fig, 'alive_energy', curves, sources, 'Right-continuous sampled series; LND zero state carried forward; 95% bands are pointwise, not simultaneous.')
    if demo_directory is not None:
        path = demo_directory / 'diamond/detector_windows.csv'
        frame = pd.read_csv(path)
        relay = frame[frame['relay_id'] == 'a']
        if not relay.empty:
            fig, axis = plt.subplots(figsize=(10, 4))
            axis.plot(relay['time_s'], relay['trust'], label='EWMA trust', color='#7c3aed')
            valid = relay[relay['status'] == 'valid']
            axis.scatter(valid['time_s'], valid['forwarding_ratio'], label='FR, mature cohort', marker='s', color='#0f766e')
            events = pd.read_csv(demo_directory / 'diamond/detector_events.csv')
            for kind, color in (('suspected', '#c2410c'), ('isolated', '#111827'), ('probation', '#2563eb')):
                times = events[(events['relay_id'] == 'a') & (events['event'] == kind)]['time_s']
                for index, when in enumerate(times):
                    axis.axvline(when, color=color, linestyle='--', label=kind if index == 0 else None)
            axis.set_xlabel('Simulation time [s]')
            axis.set_ylabel('FR / trust [0..1]')
            axis.set_ylim(-0.05, 1.05)
            axis.legend()
            axis.set_title('Single TEST_ONLY known-graph probe trace, relay a; no CI; not evaluation')
            save(fig, 'debug_FR_trust', relay.to_dict('records'), [path, demo_directory / 'diamond/detector_events.csv'], 'Empty cohorts have FR=NA, not zero. Debug thresholds are separate from frozen research settings.')
    (directory / 'figure_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return manifest
