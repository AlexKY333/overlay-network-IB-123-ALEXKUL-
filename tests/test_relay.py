import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from tunnel import Tunnel
from relay import Relay


def create_tunnel():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.add_relay(2)
    tunnel.add_relay(3)
    tunnel.add_relay(4)

    tunnel.activate()

    return tunnel


def test_relay_creation():
    tunnel = create_tunnel()

    relay = Relay(
        node_id=2,
        tunnel=tunnel,
        position=0,
    )

    assert relay.node_id == 2
    assert relay.position == 0


def test_first_relay_next_hop():
    tunnel = create_tunnel()

    relay = Relay(
        node_id=2,
        tunnel=tunnel,
        position=0,
    )

    assert relay.next_hop == 3


def test_second_relay_next_hop():
    tunnel = create_tunnel()

    relay = Relay(
        node_id=3,
        tunnel=tunnel,
        position=1,
    )

    assert relay.next_hop == 4


def test_last_relay_forwards_to_destination():
    tunnel = create_tunnel()

    relay = Relay(
        node_id=4,
        tunnel=tunnel,
        position=2,
    )

    assert relay.next_hop == 10


def test_previous_hop():
    tunnel = create_tunnel()

    relay1 = Relay(
        node_id=2,
        tunnel=tunnel,
        position=0,
    )

    relay2 = Relay(
        node_id=3,
        tunnel=tunnel,
        position=1,
    )

    relay3 = Relay(
        node_id=4,
        tunnel=tunnel,
        position=2,
    )

    assert relay1.previous_hop == 1
    assert relay2.previous_hop == 2
    assert relay3.previous_hop == 3


def test_forward_message():
    tunnel = create_tunnel()

    relay = Relay(
        node_id=2,
        tunnel=tunnel,
        position=0,
    )

    result = relay.forward(
        b"Hello through tunnel"
    )

    assert result["relay"] == 2
    assert result["next_hop"] == 3
    assert result["message"] == b"Hello through tunnel"


def test_inactive_tunnel_cannot_forward():
    tunnel = create_tunnel()
    tunnel.close()

    relay = Relay(
        node_id=2,
        tunnel=tunnel,
        position=0,
    )

    with pytest.raises(RuntimeError):
        relay.forward(b"test")


def test_relay_must_belong_to_tunnel():
    tunnel = create_tunnel()

    with pytest.raises(ValueError):
        Relay(
            node_id=99,
            tunnel=tunnel,
            position=0,
        )


def test_invalid_relay_position():
    tunnel = create_tunnel()

    with pytest.raises(ValueError):
        Relay(
            node_id=2,
            tunnel=tunnel,
            position=3,
        )