from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from contact import Contact
from lookup import IterativeLookup


def make_node_id(value: int) -> str:
    return f"{value:064x}"


def make_contact(value: int) -> Contact:
    return Contact(
        node_id=make_node_id(value),
        host="127.0.0.1",
        port=9000,
    )


def test_alpha_three():
    contacts = [
        make_contact(1),
        make_contact(2),
        make_contact(4),
        make_contact(8),
        make_contact(16),
    ]

    lookup = IterativeLookup(
        target_node_id=make_node_id(3),
        contacts=contacts,
    )

    batch = lookup.next_batch()

    values = [
        int(candidate.contact.node_id, 16)
        for candidate in batch
    ]

    assert values == [2, 1, 4]

    assert len(batch) == 3