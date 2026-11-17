import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from contact import Contact
from identity import Identity
from routing_table import RoutingTable
from sybil_guard import SybilEclipseGuard


def make_contact(host: str, port: int) -> Contact:
    state_dir = tempfile.mkdtemp()
    identity = Identity(state_dir)

    return Contact(
        node_id=identity.node_id,
        host=host,
        port=port,
    )


def make_routing_table():
    state_dir = tempfile.mkdtemp()
    identity = Identity(state_dir)

    guard = SybilEclipseGuard(
        max_contacts_per_host=1,
        max_contacts_per_subnet=2,
    )

    table = RoutingTable(
        local_node_id=identity.node_id,
        sybil_guard=guard,
    )

    return table


def test_sybil_attack_is_limited_by_subnet():
    """
    Несколько разных NodeID находятся
    в одной и той же /24 подсети.

    Guard должен разрешить только
    max_contacts_per_subnet контакта.
    """

    table = make_routing_table()

    sybil_contacts = [
        make_contact("10.10.10.1", 10001),
        make_contact("10.10.10.2", 10002),
        make_contact("10.10.10.3", 10003),
        make_contact("10.10.10.4", 10004),
        make_contact("10.10.10.5", 10005),
    ]

    accepted = 0
    rejected = 0

    for contact in sybil_contacts:
        try:
            table.add_contact(contact)
            accepted += 1
        except ValueError:
            rejected += 1

    assert accepted == 2
    assert rejected == 3
    assert len(table.get_contacts()) == 2


def test_legitimate_nodes_from_different_subnets_are_accepted():
    """
    Легитимные узлы находятся в разных подсетях.

    Они не должны блокироваться
    subnet diversity-защитой.
    """

    table = make_routing_table()

    legitimate_contacts = [
        make_contact("10.20.1.10", 11001),
        make_contact("10.20.2.10", 11002),
        make_contact("10.20.3.10", 11003),
        make_contact("10.20.4.10", 11004),
    ]

    for contact in legitimate_contacts:
        table.add_contact(contact)

    assert len(table.get_contacts()) == 4


def test_sybil_nodes_cannot_fill_routing_table_with_different_node_ids():
    """
    Каждый злоумышленник получает новый NodeID,
    но все находятся в одной подсети.

    Проверяем, что уникальные NodeID
    не позволяют обойти subnet limit.
    """

    table = make_routing_table()

    contacts = [
        make_contact("192.168.50.1", 12001),
        make_contact("192.168.50.2", 12002),
        make_contact("192.168.50.3", 12003),
        make_contact("192.168.50.4", 12004),
        make_contact("192.168.50.5", 12005),
        make_contact("192.168.50.6", 12006),
        make_contact("192.168.50.7", 12007),
        make_contact("192.168.50.8", 12008),
    ]

    node_ids = {
        contact.node_id
        for contact in contacts
    }

    assert len(node_ids) == 8

    accepted = 0

    for contact in contacts:
        try:
            table.add_contact(contact)
            accepted += 1
        except ValueError:
            pass

    assert accepted == 2
    assert len(table.get_contacts()) == 2


def test_legitimate_nodes_remain_after_sybil_attack():
    """
    Сначала злоумышленник пытается заполнить таблицу,
    затем приходят легитимные узлы из других подсетей.

    Проверяем, что защита не блокирует
    нормальные контакты после Sybil-попытки.
    """

    table = make_routing_table()

    sybil_contacts = [
        make_contact("172.16.100.1", 13001),
        make_contact("172.16.100.2", 13002),
        make_contact("172.16.100.3", 13003),
        make_contact("172.16.100.4", 13004),
    ]

    for contact in sybil_contacts:
        try:
            table.add_contact(contact)
        except ValueError:
            pass

    legitimate_contacts = [
        make_contact("172.16.101.10", 13101),
        make_contact("172.16.102.10", 13201),
        make_contact("172.16.103.10", 13301),
    ]

    for contact in legitimate_contacts:
        table.add_contact(contact)

    contacts = table.get_contacts()

    assert len(contacts) == 5

    legitimate_ids = {
        contact.node_id
        for contact in legitimate_contacts
    }

    table_ids = {
        contact.node_id
        for contact in contacts
    }

    assert legitimate_ids.issubset(table_ids)


def test_sybil_nodes_cannot_displace_existing_legitimate_contacts():
    """
    Реалистичный Eclipse-сценарий.

    Сначала в routing table находятся
    легитимные контакты.

    Затем атакующий пытается добавить
    большое количество Sybil-узлов из
    одной подсети.

    Защита должна не позволить Sybil-узлам
    вытеснить существующие легитимные контакты.
    """

    table = make_routing_table()

    legitimate_contacts = [
        make_contact("10.30.1.10", 14001),
        make_contact("10.30.2.10", 14002),
        make_contact("10.30.3.10", 14003),
        make_contact("10.30.4.10", 14004),
    ]

    for contact in legitimate_contacts:
        table.add_contact(contact)

    legitimate_ids_before = {
        contact.node_id
        for contact in table.get_contacts()
    }

    sybil_contacts = [
        make_contact("10.99.99.1", 15001),
        make_contact("10.99.99.2", 15002),
        make_contact("10.99.99.3", 15003),
        make_contact("10.99.99.4", 15004),
        make_contact("10.99.99.5", 15005),
        make_contact("10.99.99.6", 15006),
        make_contact("10.99.99.7", 15007),
        make_contact("10.99.99.8", 15008),
        make_contact("10.99.99.9", 15009),
        make_contact("10.99.99.10", 15010),
    ]

    for contact in sybil_contacts:
        try:
            table.add_contact(contact)
        except ValueError:
            pass

    legitimate_ids_after = {
        contact.node_id
        for contact in table.get_contacts()
    }

    assert legitimate_ids_before.issubset(
        legitimate_ids_after
    )


def test_large_sybil_group_cannot_capture_table():
    """
    Массовая Sybil-атака:

    20 разных NodeID находятся
    в одной /24 подсети.

    При лимите 2 контакта на подсеть
    только два должны быть приняты.
    """

    table = make_routing_table()

    sybil_contacts = [
        make_contact(
            f"192.168.200.{i}",
            16000 + i,
        )
        for i in range(1, 21)
    ]

    accepted = 0
    rejected = 0

    for contact in sybil_contacts:
        try:
            table.add_contact(contact)
            accepted += 1
        except ValueError:
            rejected += 1

    assert accepted == 2
    assert rejected == 18

    contacts = table.get_contacts()

    assert len(contacts) == 2