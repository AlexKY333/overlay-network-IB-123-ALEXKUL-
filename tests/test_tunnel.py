import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from tunnel import Tunnel, TunnelState


def test_tunnel_creation():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    assert tunnel.source_node_id == 1
    assert tunnel.destination_node_id == 10
    assert tunnel.relay_count == 0
    assert tunnel.state == TunnelState.CREATING
    assert tunnel.is_active() is False


def test_add_relays():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.add_relay(2)
    tunnel.add_relay(3)
    tunnel.add_relay(4)

    assert tunnel.relay_node_ids == [2, 3, 4]
    assert tunnel.relay_count == 3
    assert tunnel.path == [1, 2, 3, 4, 10]


def test_tunnel_activation():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    assert tunnel.state == TunnelState.CREATING

    tunnel.activate()

    assert tunnel.state == TunnelState.ACTIVE
    assert tunnel.is_active() is True


def test_tunnel_close():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.activate()
    tunnel.close()

    assert tunnel.state == TunnelState.CLOSED
    assert tunnel.is_active() is False


def test_cannot_add_duplicate_relay():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.add_relay(2)

    with pytest.raises(ValueError):
        tunnel.add_relay(2)


def test_source_cannot_be_relay():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    with pytest.raises(ValueError):
        tunnel.add_relay(1)


def test_destination_cannot_be_relay():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    with pytest.raises(ValueError):
        tunnel.add_relay(10)


def test_cannot_activate_closed_tunnel():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.close()

    with pytest.raises(RuntimeError):
        tunnel.activate()


def test_cannot_add_relay_to_closed_tunnel():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.close()

    with pytest.raises(RuntimeError):
        tunnel.add_relay(2)