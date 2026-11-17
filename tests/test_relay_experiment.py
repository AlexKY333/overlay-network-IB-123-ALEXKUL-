import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from relay_experiment import run_experiment
from relay_profile import RelayProfile


def make_profile(
    node_id: int,
    success: int,
    latency: float,
    consecutive_failures: int = 0,
) -> RelayProfile:

    profile = RelayProfile(
        node_id=node_id,
    )

    for _ in range(success):
        profile.record_success(
            latency=latency
        )

    profile.consecutive_failures = (
        consecutive_failures
    )

    return profile


def test_experiment_returns_expected_structure():
    profiles = [
        make_profile(1, 5, 0.1),
        make_profile(2, 5, 0.2),
        make_profile(3, 5, 0.3),
    ]

    result = run_experiment(
        profiles,
        iterations=100,
    )

    assert result["iterations"] == 100
    assert result["candidate_count"] == 3
    assert result["admissible_count"] == 3

    assert "random" in result
    assert "ranked" in result

    assert (
        "selection_counts"
        in result["random"]
    )

    assert (
        "selection_counts"
        in result["ranked"]
    )

    assert (
        "average_latency"
        in result["random"]
    )

    assert (
        "average_latency"
        in result["ranked"]
    )


def test_ranked_strategy_prefers_best_relay():
    profiles = [
        make_profile(
            node_id=1,
            success=3,
            latency=1.0,
        ),
        make_profile(
            node_id=2,
            success=3,
            latency=0.5,
        ),
        make_profile(
            node_id=3,
            success=3,
            latency=0.1,
        ),
    ]

    result = run_experiment(
        profiles,
        iterations=100,
    )

    ranked = result["ranked"]["selection_counts"]

    assert ranked.get(3, 0) == 100
    assert ranked.get(1, 0) == 0
    assert ranked.get(2, 0) == 0


def test_unhealthy_relay_is_not_selected():
    profiles = [
        make_profile(
            node_id=1,
            success=10,
            latency=0.01,
            consecutive_failures=3,
        ),
        make_profile(
            node_id=2,
            success=3,
            latency=0.2,
        ),
        make_profile(
            node_id=3,
            success=3,
            latency=0.3,
        ),
    ]

    result = run_experiment(
        profiles,
        iterations=100,
    )

    assert (
        result["random"]["selection_counts"]
        .get(1, 0)
        == 0
    )

    assert (
        result["ranked"]["selection_counts"]
        .get(1, 0)
        == 0
    )


def test_ranked_latency_is_better_than_random():
    profiles = [
        make_profile(
            node_id=1,
            success=3,
            latency=1.0,
        ),
        make_profile(
            node_id=2,
            success=3,
            latency=0.5,
        ),
        make_profile(
            node_id=3,
            success=3,
            latency=0.1,
        ),
    ]

    result = run_experiment(
        profiles,
        iterations=1000,
    )

    assert (
        result["ranked"]["average_latency"]
        <= result["random"]["average_latency"]
    )


def test_invalid_iterations_rejected():
    profiles = [
        make_profile(
            node_id=1,
            success=3,
            latency=0.1,
        ),
    ]

    try:
        run_experiment(
            profiles,
            iterations=0,
        )
    except ValueError:
        return

    raise AssertionError(
        "iterations=0 must raise ValueError"
    )