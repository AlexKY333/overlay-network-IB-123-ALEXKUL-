import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from relay_profile import RelayProfile
from relay_selector import RelaySelector


def make_profile(
    node_id: int,
    success: int = 0,
    failures: int = 0,
    latency: float | None = None,
    consecutive_failures: int = 0,
) -> RelayProfile:
    profile = RelayProfile(
        node_id=node_id,
    )

    for _ in range(success):
        profile.record_success(
            latency=latency or 0.1,
        )

    for _ in range(failures):
        profile.record_failure()

    profile.consecutive_failures = consecutive_failures

    return profile


def test_selector_starts_empty():
    selector = RelaySelector()

    assert selector.list_profiles() == []
    assert selector.admissible_profiles() == []


def test_add_profile():
    selector = RelaySelector()

    profile = RelayProfile(node_id=10)

    selector.add_profile(profile)

    assert selector.get_profile(10) is profile
    assert selector.list_profiles() == [profile]


def test_duplicate_profile_rejected():
    selector = RelaySelector()

    selector.add_profile(
        RelayProfile(node_id=10)
    )

    with pytest.raises(ValueError):
        selector.add_profile(
            RelayProfile(node_id=10)
        )


def test_invalid_profile_rejected():
    selector = RelaySelector()

    with pytest.raises(TypeError):
        selector.add_profile("invalid")


def test_unhealthy_profiles_are_excluded():
    healthy = make_profile(
        node_id=1,
        consecutive_failures=0,
    )

    unhealthy = make_profile(
        node_id=2,
        consecutive_failures=3,
    )

    selector = RelaySelector(
        [
            healthy,
            unhealthy,
        ]
    )

    candidates = selector.admissible_profiles()

    assert healthy in candidates
    assert unhealthy not in candidates


def test_random_selection_returns_admissible_profile():
    profile1 = make_profile(
        node_id=1,
    )

    profile2 = make_profile(
        node_id=2,
    )

    selector = RelaySelector(
        [
            profile1,
            profile2,
        ]
    )

    selected = selector.select_random()

    assert selected in [
        profile1,
        profile2,
    ]


def test_random_selection_without_candidates_fails():
    selector = RelaySelector()

    with pytest.raises(RuntimeError):
        selector.select_random()


def test_ranked_selection_prefers_successful_fast_relay():
    slow = make_profile(
        node_id=1,
        success=3,
        latency=1.0,
    )

    fast = make_profile(
        node_id=2,
        success=3,
        latency=0.1,
    )

    selector = RelaySelector(
        [
            slow,
            fast,
        ]
    )

    selected = selector.select_ranked()

    assert selected is fast


def test_ranked_selection_avoids_unhealthy_relay():
    good = make_profile(
        node_id=1,
        success=3,
        latency=0.2,
    )

    bad = make_profile(
        node_id=2,
        success=10,
        latency=0.01,
        consecutive_failures=3,
    )

    selector = RelaySelector(
        [
            good,
            bad,
        ]
    )

    selected = selector.select_ranked()

    assert selected is good


def test_ranked_selection_prefers_higher_ema_success():
    good = RelayProfile(
        node_id=1,
        ema_success=0.95,
        ema_latency=0.2,
    )

    bad = RelayProfile(
        node_id=2,
        ema_success=0.40,
        ema_latency=0.2,
    )

    selector = RelaySelector(
        [
            good,
            bad,
        ]
    )

    selected = selector.select_ranked()

    assert selected is good


def test_ranked_selection_without_candidates_fails():
    selector = RelaySelector()

    with pytest.raises(RuntimeError):
        selector.select_ranked()


def test_invalid_failure_threshold_rejected():
    with pytest.raises(ValueError):
        RelaySelector(
            max_consecutive_failures=-1
        )


def test_score_rewards_lower_latency():
    fast = RelayProfile(
        node_id=1,
        ema_success=0.8,
        ema_latency=0.1,
    )

    slow = RelayProfile(
        node_id=2,
        ema_success=0.8,
        ema_latency=1.0,
    )

    assert (
        RelaySelector._score(fast)
        > RelaySelector._score(slow)
    )