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


def test_initial_profile():
    profile = RelayProfile(node_id=10)

    assert profile.node_id == 10
    assert profile.subnet is None

    assert profile.success_count == 0
    assert profile.failure_count == 0

    assert profile.total_observations == 0
    assert profile.success_rate == 0.0

    assert profile.ema_success == 1.0
    assert profile.ema_latency is None

    assert profile.last_observation is None
    assert profile.consecutive_failures == 0


def test_success_updates_statistics():
    profile = RelayProfile(
        node_id=10,
        subnet="10.0.0.0/24",
    )

    profile.record_success(
        latency=0.100,
        observed_at=100.0,
    )

    assert profile.success_count == 1
    assert profile.failure_count == 0

    assert profile.total_observations == 1
    assert profile.success_rate == 1.0

    assert profile.ema_latency == pytest.approx(0.100)

    assert profile.last_observation == 100.0
    assert profile.consecutive_failures == 0


def test_failure_updates_statistics():
    profile = RelayProfile(
        node_id=10,
        subnet="10.0.0.0/24",
    )

    profile.record_failure(
        observed_at=200.0,
    )

    assert profile.success_count == 0
    assert profile.failure_count == 1

    assert profile.total_observations == 1
    assert profile.success_rate == 0.0

    assert profile.last_observation == 200.0
    assert profile.consecutive_failures == 1

    assert profile.ema_success == pytest.approx(0.8)


def test_consecutive_failures_increase():
    profile = RelayProfile(node_id=10)

    profile.record_failure(observed_at=1.0)
    profile.record_failure(observed_at=2.0)
    profile.record_failure(observed_at=3.0)

    assert profile.failure_count == 3
    assert profile.consecutive_failures == 3


def test_success_resets_consecutive_failures():
    profile = RelayProfile(node_id=10)

    profile.record_failure(observed_at=1.0)
    profile.record_failure(observed_at=2.0)

    assert profile.consecutive_failures == 2

    profile.record_success(
        latency=0.050,
        observed_at=3.0,
    )

    assert profile.consecutive_failures == 0
    assert profile.success_count == 1
    assert profile.failure_count == 2


def test_ema_success_changes_after_failure():
    profile = RelayProfile(
        node_id=10,
        ema_alpha=0.2,
    )

    profile.record_failure(observed_at=1.0)

    assert profile.ema_success == pytest.approx(0.8)

    profile.record_failure(observed_at=2.0)

    assert profile.ema_success == pytest.approx(0.64)


def test_ema_latency():
    profile = RelayProfile(
        node_id=10,
        ema_alpha=0.5,
    )

    profile.record_success(
        latency=0.100,
        observed_at=1.0,
    )

    assert profile.ema_latency == pytest.approx(0.100)

    profile.record_success(
        latency=0.300,
        observed_at=2.0,
    )

    assert profile.ema_latency == pytest.approx(0.200)


def test_negative_latency_rejected():
    profile = RelayProfile(node_id=10)

    with pytest.raises(ValueError):
        profile.record_success(
            latency=-0.001,
        )


def test_invalid_ema_alpha_rejected():
    with pytest.raises(ValueError):
        RelayProfile(
            node_id=10,
            ema_alpha=0.0,
        )

    with pytest.raises(ValueError):
        RelayProfile(
            node_id=10,
            ema_alpha=1.5,
        )


def test_health_status():
    profile = RelayProfile(node_id=10)

    assert profile.is_healthy() is True

    profile.record_failure(observed_at=1.0)
    profile.record_failure(observed_at=2.0)

    assert profile.is_healthy() is True

    profile.record_failure(observed_at=3.0)

    assert profile.is_healthy() is False


def test_reset_failures():
    profile = RelayProfile(node_id=10)

    profile.record_failure(observed_at=1.0)
    profile.record_failure(observed_at=2.0)

    assert profile.consecutive_failures == 2

    profile.reset_failures()

    assert profile.consecutive_failures == 0