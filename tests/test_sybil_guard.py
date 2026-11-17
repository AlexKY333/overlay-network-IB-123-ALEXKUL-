from pathlib import Path
import sys

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from contact import Contact
from sybil_guard import SybilEclipseGuard


def make_node_id(value: int) -> str:
    return f"{value:064x}"


def test_duplicate_node_id_is_rejected():

    guard = SybilEclipseGuard()

    existing = [
        Contact(
            node_id=make_node_id(1),
            host="10.0.0.1",
            port=9001,
        )
    ]

    candidate = Contact(
        node_id=make_node_id(1),
        host="10.0.0.2",
        port=9002,
    )

    allowed, reason = guard.check_contact(
        candidate,
        existing,
    )

    assert allowed is False
    assert reason == "duplicate_node_id"


def test_second_contact_from_same_host_is_rejected():

    guard = SybilEclipseGuard(
        max_contacts_per_host=1,
        max_contacts_per_subnet=4,
    )

    existing = [
        Contact(
            node_id=make_node_id(1),
            host="10.0.0.10",
            port=9001,
        )
    ]

    candidate = Contact(
        node_id=make_node_id(2),
        host="10.0.0.10",
        port=9002,
    )

    allowed, reason = guard.check_contact(
        candidate,
        existing,
    )

    assert allowed is False
    assert reason == "host_limit_exceeded"


def test_subnet_diversity_limit():

    guard = SybilEclipseGuard(
        max_contacts_per_host=2,
        max_contacts_per_subnet=2,
    )

    existing = [
        Contact(
            node_id=make_node_id(1),
            host="10.20.30.1",
            port=9001,
        ),
        Contact(
            node_id=make_node_id(2),
            host="10.20.30.2",
            port=9002,
        ),
    ]

    candidate = Contact(
        node_id=make_node_id(3),
        host="10.20.30.3",
        port=9003,
    )

    allowed, reason = guard.check_contact(
        candidate,
        existing,
    )

    assert allowed is False
    assert reason == "subnet_limit_exceeded"


def test_different_subnet_is_allowed():

    guard = SybilEclipseGuard(
        max_contacts_per_host=1,
        max_contacts_per_subnet=2,
    )

    existing = [
        Contact(
            node_id=make_node_id(1),
            host="10.20.30.1",
            port=9001,
        ),
        Contact(
            node_id=make_node_id(2),
            host="10.20.30.2",
            port=9002,
        ),
    ]

    candidate = Contact(
        node_id=make_node_id(3),
        host="10.20.31.1",
        port=9003,
    )

    allowed, reason = guard.check_contact(
        candidate,
        existing,
    )

    assert allowed is True
    assert reason == "accepted"


def test_ipv6_subnet_diversity():

    guard = SybilEclipseGuard(
        max_contacts_per_host=1,
        max_contacts_per_subnet=2,
    )

    existing = [
        Contact(
            node_id=make_node_id(1),
            host="2001:db8:1::1",
            port=9001,
        ),
        Contact(
            node_id=make_node_id(2),
            host="2001:db8:1::2",
            port=9002,
        ),
    ]

    candidate = Contact(
        node_id=make_node_id(3),
        host="2001:db8:1::3",
        port=9003,
    )

    allowed, reason = guard.check_contact(
        candidate,
        existing,
    )

    assert allowed is False
    assert reason == "subnet_limit_exceeded"


def test_hostname_is_not_rejected():

    guard = SybilEclipseGuard()

    candidate = Contact(
        node_id=make_node_id(1),
        host="node.example",
        port=9001,
    )

    allowed, reason = guard.check_contact(
        candidate,
        [],
    )

    assert allowed is True
    assert reason == "accepted_non_ip_host"