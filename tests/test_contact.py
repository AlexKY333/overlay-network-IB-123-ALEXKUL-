from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from contact import Contact
from contact import node_id_to_int
from contact import xor_distance


def test_contact():
    # -----------------------------------
    # 1. Проверяем преобразование NodeID
    # -----------------------------------

    value = node_id_to_int("0f")

    assert value == 15

    print("NodeID -> int: PASS")

    # -----------------------------------
    # 2. Проверяем XOR distance
    # -----------------------------------

    distance = xor_distance(
        "0f",
        "03",
    )

    assert distance == 12

    print("XOR distance: PASS")

    # -----------------------------------
    # 3. Расстояние самого узла до себя
    # -----------------------------------

    distance = xor_distance(
        "1234",
        "1234",
    )

    assert distance == 0

    print("Distance to self: PASS")

    # -----------------------------------
    # 4. XOR должен быть симметричным
    # -----------------------------------

    distance_ab = xor_distance(
        "0f",
        "03",
    )

    distance_ba = xor_distance(
        "03",
        "0f",
    )

    assert distance_ab == distance_ba

    print("XOR symmetry: PASS")

    # -----------------------------------
    # 5. Проверяем Contact
    # -----------------------------------

    contact = Contact(
        node_id="a1b2c3",
        host="127.0.0.1",
        port=9001,
    )

    assert contact.node_id == "a1b2c3"
    assert contact.host == "127.0.0.1"
    assert contact.port == 9001
    assert contact.last_seen is None

    print("Contact: PASS")

    print("\nCONTACT TEST PASSED")


if __name__ == "__main__":
    test_contact()