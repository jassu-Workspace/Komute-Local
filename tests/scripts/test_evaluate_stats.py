import pytest

from scripts.evaluate import clopper_pearson, pick_threshold, required_impostor_trials, split_by_person


def test_clopper_pearson_zero_failures_upper_bound():
    lo, hi = clopper_pearson(0, 100)
    assert lo == 0.0 and hi == pytest.approx(0.0362, abs=1e-3)


def test_clopper_pearson_contains_the_point_estimate():
    lo, hi = clopper_pearson(5, 100)
    assert lo < 0.05 < hi


def test_clopper_pearson_edges():
    assert clopper_pearson(0, 0) == (0.0, 1.0)
    assert clopper_pearson(10, 10)[1] == 1.0


def test_split_by_person_never_shares_a_person_and_is_deterministic():
    rows = [{"person_id": f"p{i % 40}", "n": i} for i in range(400)]
    tune, hold = split_by_person(rows)
    assert {r["person_id"] for r in tune}.isdisjoint({r["person_id"] for r in hold})
    assert len(tune) + len(hold) == 400 and hold and tune
    assert split_by_person(rows) == (tune, hold)


def test_pick_threshold_above_all_impostors_at_zero_far():
    assert pick_threshold([0.6, 0.7], [0.1, 0.2, 0.45], 0.0) > 0.45


def test_pick_threshold_allows_the_stated_fraction():
    impostor = [i / 100 for i in range(100)]
    t = pick_threshold([0.9], impostor, 0.05)
    assert sum(x >= t for x in impostor) <= 5


def test_pick_threshold_needs_impostors():
    with pytest.raises(ValueError):
        pick_threshold([0.5], [], 0.01)


def test_required_trials_for_one_in_ten_thousand():
    assert 29950 <= required_impostor_trials(1e-4) <= 29960
