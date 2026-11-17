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


def test_find_closest():
    table = RoutingTable(
        local_node_id=make_node_id(0)
    )

    # Добавляем несколько узлов.
    for value in [1, 2, 4, 8, 16, 32]:
        table.add_contact(
            make_contact(value)
        )

    # Ищем 4 ближайших к target = 3.
    closest = table.find_closest_nodes(
        target_node_id=make_node_id(3),
        count=4,
    )

    values = [
        int(contact.node_id, 16)
        for contact in closest
    ]

    # XOR distances:
    #
    # 1 ^ 3 = 2
    # 2 ^ 3 = 1
    # 4 ^ 3 = 7
    # 8 ^ 3 = 11
    # 16 ^ 3 = 19
    # 32 ^ 3 = 35
    #
    # Поэтому порядок:
    # 2, 1, 4, 8

    assert values == [2, 1, 4, 8]

    print("XOR closest nodes: PASS")

    # Проверяем ограничение количества.
    assert len(closest) == 4

    print("Result limited to 4 nodes: PASS")

    # Проверяем, что можно запросить меньше.
    closest_two = table.find_closest_nodes(
        target_node_id=make_node_id(3),
        count=2,
    )

    assert [
        int(contact.node_id, 16)
        for contact in closest_two
    ] == [2, 1]

    print("Custom result count: PASS")

    print("\nFIND CLOSEST TEST PASSED")


if __name__ == "__main__":
    test_find_closest()