import pytest
from wsn_sim.experiment_statistics import holm_adjust, paired_comparison, restricted_lifetime_summary, sample_summary

def test_student_t_ci_matches_hand_three_seed_example():
    result = sample_summary([1, 2, 3], 3)
    assert result['mean'] == 2 and result['sample_std_ddof1'] == 1
    assert result['ci95_low'] == pytest.approx(-0.4841377117)
    assert result['ci95_high'] == pytest.approx(4.4841377117)
    assert result['n_used'] == 3 and (not result['meets_30_seed_requirement'])

def test_one_seed_has_no_ci_and_missing_values_keep_denominator():
    result = sample_summary([0.5, None], 30)
    assert result['mean'] == 0.5 and result['ci95_low'] is None
    assert result['n_used'] == 1 and result['n_missing'] == 29
    with pytest.raises(ValueError, match='non-finite'):
        sample_summary([float('nan')])

def test_censored_lifetime_is_restricted_not_observed_only_mean():
    result = restricted_lifetime_summary([{'time_s': 2}, {'time_s': None}], [10, 10])
    assert result['restricted']['mean'] == 6
    assert result['observed_only_conditional']['mean'] == 2
    assert result['censored'] == 1 and result['event_coverage'] == 0.5
    assert not result['unrestricted_mean_claimed']

def test_zero_and_constant_paired_differences_are_explicit():
    result = paired_comparison({1: 3, 2: 5}, {1: 3, 2: 5}, 30)
    assert result['paired_t_p'] == result['wilcoxon_p'] == 1
    assert result['cohen_dz'] == result['rank_biserial_nonzero_pairs'] == 0
    constant = paired_comparison({1: 4, 2: 6, 3: 8}, {1: 3, 2: 5, 3: 7}, 3)
    assert constant['mean_difference_first_minus_second'] == 1
    assert constant['paired_t_p'] is None and constant['rank_biserial_nonzero_pairs'] == 1

def test_pairing_uses_seed_intersection_and_reports_actual_n():
    result = paired_comparison({1: 1, 2: 2, 3: None}, {2: 4, 3: 5, 4: 6}, 30)
    assert result['matched_seeds'] == [2] and result['n_matched'] == 1
    assert result['paired_t_p'] is None

def test_holm_preserves_family_size_including_missing_tests():
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    adjusted = holm_adjust([0.01, None, 0.03])
    assert adjusted[0] == 0.03 and adjusted[1] is None and (adjusted[2] == 0.06)
