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
from tunnel import TunnelState
from tunnel_builder import TunnelBuilder
from tunnel_pool import TunnelPool


def make_profile(
    node_id: int,
    success: int = 3,
    latency: float = 0.1,
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


def test_ranked_builder_creates_active_tunnel():
    profiles = [
        make_profile(10, latency=0.1),
        make_profile(20, latency=0.2),
        make_profile(30, latency=0.3),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    tunnel = builder.build(
        source_node_id=1,
        destination_node_id=100,
        relay_count=3,
        strategy="ranked",
    )

    assert tunnel.state == TunnelState.ACTIVE
    assert tunnel.source_node_id == 1
    assert tunnel.destination_node_id == 100
    assert tunnel.relay_count == 3


def test_ranked_builder_prefers_best_relays():
    profiles = [
        make_profile(10, latency=1.0),
        make_profile(20, latency=0.5),
        make_profile(30, latency=0.1),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    tunnel = builder.build(
        source_node_id=1,
        destination_node_id=100,
        relay_count=2,
        strategy="ranked",
    )

    assert tunnel.relay_node_ids == [30, 20]


def test_builder_does_not_repeat_relays():
    profiles = [
        make_profile(10),
        make_profile(20),
        make_profile(30),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    tunnel = builder.build(
        source_node_id=1,
        destination_node_id=100,
        relay_count=3,
    )

    assert len(tunnel.relay_node_ids) == 3
    assert len(set(tunnel.relay_node_ids)) == 3


def test_builder_excludes_unhealthy_relay():
    profiles = [
        make_profile(
            10,
            latency=0.01,
            consecutive_failures=3,
        ),
        make_profile(
            20,
            latency=0.2,
        ),
        make_profile(
            30,
            latency=0.3,
        ),
        make_profile(
            40,
            latency=0.4,
        ),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    tunnel = builder.build(
        source_node_id=1,
        destination_node_id=100,
        relay_count=3,
    )

    assert 10 not in tunnel.relay_node_ids
    assert len(tunnel.relay_node_ids) == 3


def test_builder_adds_tunnel_to_pool():
    profiles = [
        make_profile(10),
        make_profile(20),
        make_profile(30),
    ]

    selector = RelaySelector(profiles)
    pool = TunnelPool()

    builder = TunnelBuilder(
        selector=selector,
        pool=pool,
    )

    tunnel = builder.build(
        source_node_id=1,
        destination_node_id=100,
        relay_count=3,
    )

    assert pool.size == 1
    assert pool.active_count == 1
    assert pool.get(
        str(tunnel.tunnel_id)
    ) is tunnel


def test_builder_supports_random_strategy():
    profiles = [
        make_profile(10),
        make_profile(20),
        make_profile(30),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    tunnel = builder.build(
        source_node_id=1,
        destination_node_id=100,
        relay_count=2,
        strategy="random",
    )

    assert tunnel.relay_count == 2
    assert len(
        set(tunnel.relay_node_ids)
    ) == 2


def test_not_enough_relays_rejected():
    profiles = [
        make_profile(10),
        make_profile(20),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    with pytest.raises(RuntimeError):
        builder.build(
            source_node_id=1,
            destination_node_id=100,
            relay_count=3,
        )


def test_invalid_strategy_rejected():
    profiles = [
        make_profile(10),
        make_profile(20),
        make_profile(30),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    with pytest.raises(ValueError):
        builder.build(
            source_node_id=1,
            destination_node_id=100,
            relay_count=3,
            strategy="unknown",
        )


def test_same_source_and_destination_rejected():
    profiles = [
        make_profile(10),
        make_profile(20),
        make_profile(30),
    ]

    selector = RelaySelector(profiles)
    builder = TunnelBuilder(selector)

    with pytest.raises(ValueError):
        builder.build(
            source_node_id=1,
            destination_node_id=1,
            relay_count=3,
        )