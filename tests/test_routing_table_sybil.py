from pathlib import Path
import sys

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from contact import Contact
from routing_table import RoutingTable
from sybil_guard import SybilEclipseGuard


def make_node_id(value: int) -> str:
    return f"{value:064x}"


def test_routing_table_rejects_duplicate_node_id():

    guard = SybilEclipseGuard(
        max_contacts_per_host=2,
        max_contacts_per_subnet=4,
    )

    table = RoutingTable(
        local_node_id=make_node_id(0),
        sybil_guard=guard,
    )

    first = Contact(
        node_id=make_node_id(1),
        host="10.10.10.1",
        port=9001,
    )

    duplicate = Contact(
        node_id=make_node_id(1),
        host="10.10.10.2",
        port=9002,
    )

    table.add_contact(first)

    with pytest.raises(
        ValueError,
        match="duplicate_node_id",
    ):
        table.add_contact(duplicate)


def test_routing_table_rejects_host_sybil():

    guard = SybilEclipseGuard(
        max_contacts_per_host=1,
        max_contacts_per_subnet=10,
    )

    table = RoutingTable(
        local_node_id=make_node_id(0),
        sybil_guard=guard,
    )

    table.add_contact(
        Contact(
            node_id=make_node_id(1),
            host="10.10.10.1",
            port=9001,
        )
    )

    with pytest.raises(
        ValueError,
        match="host_limit_exceeded",
    ):
        table.add_contact(
            Contact(
                node_id=make_node_id(2),
                host="10.10.10.1",
                port=9002,
            )
        )


def test_routing_table_rejects_subnet_eclipse():

    guard = SybilEclipseGuard(
        max_contacts_per_host=2,
        max_contacts_per_subnet=2,
    )

    table = RoutingTable(
        local_node_id=make_node_id(0),
        sybil_guard=guard,
    )

    table.add_contact(
        Contact(
            node_id=make_node_id(1),
            host="10.20.30.1",
            port=9001,
        )
    )

    table.add_contact(
        Contact(
            node_id=make_node_id(2),
            host="10.20.30.2",
            port=9002,
        )
    )

    with pytest.raises(
        ValueError,
        match="subnet_limit_exceeded",
    ):
        table.add_contact(
            Contact(
                node_id=make_node_id(3),
                host="10.20.30.3",
                port=9003,
            )
        )


def test_routing_table_accepts_different_subnet():

    guard = SybilEclipseGuard(
        max_contacts_per_host=1,
        max_contacts_per_subnet=2,
    )

    table = RoutingTable(
        local_node_id=make_node_id(0),
        sybil_guard=guard,
    )

    table.add_contact(
        Contact(
            node_id=make_node_id(1),
            host="10.20.30.1",
            port=9001,
        )
    )

    table.add_contact(
        Contact(
            node_id=make_node_id(2),
            host="10.20.31.1",
            port=9002,
        )
    )

    assert len(
        table.get_contacts()
    ) == 2