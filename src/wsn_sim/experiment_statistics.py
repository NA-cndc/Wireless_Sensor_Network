from math import isfinite, sqrt
from statistics import mean, stdev
import numpy as np
from scipy import stats

def sample_summary(values, expected=None):
    values = list(values)
    observed = [float(value) for value in values if value is not None]
    if any((not isfinite(value) for value in observed)):
        raise ValueError('non-finite values must be declared missing')
    n = len(observed)
    expected = len(values) if expected is None else expected
    if expected < n:
        raise ValueError('expected seed count cannot be below observed count')
    result = {'n_expected': expected, 'n_used': n, 'n_missing': expected - n, 'coverage': n / expected if expected else None, 'mean': mean(observed) if n else None, 'sample_std_ddof1': stdev(observed) if n > 1 else None, 'ci95_low': None, 'ci95_high': None, 'ci_method': 'Student_t_pointwise' if n > 1 else 'not_available_fewer_than_two_seeds', 'meets_30_seed_requirement': n >= 30 and n == expected}
    if n > 1:
        half = float(stats.t.ppf(0.975, n - 1)) * result['sample_std_ddof1'] / sqrt(n)
        result['ci95_low'], result['ci95_high'] = (result['mean'] - half, result['mean'] + half)
    return result

def restricted_lifetime_summary(milestones, horizons):
    if len(milestones) != len(horizons):
        raise ValueError('lifetime and horizon arrays must match')
    samples, events = ([], 0)
    for milestone, horizon in zip(milestones, horizons):
        if horizon <= 0:
            raise ValueError('horizon must be positive')
        time = milestone['time_s']
        if time is None:
            samples.append(horizon)
        else:
            if time < 0 or time > horizon:
                raise ValueError('lifetime is outside observation horizon')
            samples.append(time)
            events += 1
    common = len(set(horizons)) == 1
    return {'estimand': 'mean_min_lifetime_horizon_not_unrestricted_lifetime', 'horizon_s': horizons[0] if horizons and common else None, 'common_administrative_horizon': common, 'observed_events': events, 'censored': len(samples) - events, 'event_coverage': events / len(samples) if samples else None, 'restricted': sample_summary(samples), 'observed_only_conditional': sample_summary([row['time_s'] for row in milestones]), 'unrestricted_mean_claimed': False}

def paired_comparison(first, second, expected=None):
    keys = sorted(set(first) & set(second))
    keys = [key for key in keys if first[key] is not None and second[key] is not None]
    x, y = ([float(first[key]) for key in keys], [float(second[key]) for key in keys])
    if any((not isfinite(value) for value in x + y)):
        raise ValueError('non-finite paired data')
    differences = np.round(np.array(x) - np.array(y), 12)
    n = len(differences)
    result = {'n_expected': expected if expected is not None else len(set(first) | set(second)), 'n_matched': n, 'matched_seeds': keys, 'mean_difference_first_minus_second': float(np.mean(differences)) if n else None, 'cohen_dz': None, 'rank_biserial_nonzero_pairs': None, 'paired_t_p': None, 'wilcoxon_p': None, 'difference_shapiro_p': None, 'zero_differences': int(np.count_nonzero(differences == 0)), 'difference_rounding_decimals': 12, 'assumptions': 'paired_t_assumes_suitable_mean_difference_sampling_Wilcoxon_assumes_symmetric_differences_no_automatic_best_test_selection'}
    if n < 2:
        result['na_reason'] = 'fewer_than_two_matched_seeds'
        return result
    if np.all(differences == 0):
        result.update(paired_t_p=1.0, wilcoxon_p=1.0, cohen_dz=0.0, rank_biserial_nonzero_pairs=0.0, na_reason=None)
        return result
    sd = float(np.std(differences, ddof=1))
    if sd > 0:
        result['paired_t_p'] = float(stats.ttest_rel(x, y).pvalue)
        result['cohen_dz'] = float(np.mean(differences)) / sd
        if n >= 3:
            result['difference_shapiro_p'] = float(stats.shapiro(differences).pvalue)
    else:
        result['paired_t_na_reason'] = 'zero_variance_nonzero_differences'
    result['wilcoxon_p'] = float(stats.wilcoxon(differences, zero_method='pratt', method='auto').pvalue)
    nonzero = differences[differences != 0]
    ranks = stats.rankdata(np.abs(nonzero))
    result['rank_biserial_nonzero_pairs'] = float(np.sum(ranks * np.sign(nonzero)) / np.sum(ranks))
    return result

def holm_adjust(pvalues):
    values = list(pvalues)
    if any((value is not None and (not isfinite(value) or not 0 <= value <= 1) for value in values)):
        raise ValueError('invalid p-values')
    ordered = sorted(((value if value is not None else 1, index) for index, value in enumerate(values)))
    adjusted = [None] * len(values)
    previous = 0.0
    for rank, (value, index) in enumerate(ordered):
        previous = max(previous, min(1.0, (len(values) - rank) * value))
        if values[index] is not None:
            adjusted[index] = previous
    return adjusted
