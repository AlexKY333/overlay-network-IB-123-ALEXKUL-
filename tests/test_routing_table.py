from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from contact import Contact
from routing_table import RoutingTable


def make_node_id(value: int) -> str:
    return f"{value:064x}"


def make_contact(value: int) -> Contact:
    return Contact(
        node_id=make_node_id(value),
        host="127.0.0.1",
        port=9000 + value,
    )


def test_routing_table():
    local_node_id = make_node_id(0)

    table = RoutingTable(
        local_node_id
    )

    # -----------------------------
    # 1. Проверяем количество bucket
    # -----------------------------

    assert len(table.buckets) == 256

    print("256 buckets: PASS")

    # -----------------------------
    # 2. NodeID = 1
    #
    # XOR:
    # 0 ^ 1 = 1
    #
    # bit_length = 1
    # index = 0
    # -----------------------------

    contact = make_contact(1)

    table.add_contact(contact)

    assert len(
        table.get_bucket(0)
    ) == 1

    print("Distance 1 -> bucket 0: PASS")

    # -----------------------------
    # 3. NodeID = 2
    #
    # 0 ^ 2 = 2
    # bit_length = 2
    # index = 1
    # -----------------------------

    contact = make_contact(2)

    table.add_contact(contact)

    assert len(
        table.get_bucket(1)
    ) == 1

    print("Distance 2 -> bucket 1: PASS")

    # -----------------------------
    # 4. NodeID = 3
    #
    # 0 ^ 3 = 3
    # bit_length = 2
    # index = 1
    #
    # Поэтому 2 и 3 находятся
    # в одном bucket.
    # -----------------------------

    contact = make_contact(3)

    table.add_contact(contact)

    assert len(
        table.get_bucket(1)
    ) == 2

    print("Distance 3 -> bucket 1: PASS")

    # -----------------------------
    # 5. Проверяем общий список
    # -----------------------------

    contacts = table.get_contacts()

    assert len(contacts) == 3

    node_ids = {
        contact.node_id
        for contact in contacts
    }

    assert node_ids == {
        make_node_id(1),
        make_node_id(2),
        make_node_id(3),
    }

    print("Get all contacts: PASS")

    # -----------------------------
    # 6. Нельзя добавить самого себя
    # -----------------------------

    try:
        table.add_contact(
            make_contact(0)
        )

    except ValueError:
        print("Reject local node: PASS")

    else:
        raise AssertionError(
            "Local node was accepted"
        )

    print("\nROUTING TABLE TEST PASSED")


if __name__ == "__main__":
    test_routing_table()