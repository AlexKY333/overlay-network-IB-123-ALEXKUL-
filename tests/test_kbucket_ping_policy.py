from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from contact import Contact
from kbucket import KBucket


def make_contact(value: int) -> Contact:
    return Contact(
        node_id=f"{value:064x}",
        host="127.0.0.1",
        port=9000 + value,
    )


def test_full_bucket_returns_oldest_contact():

    bucket = KBucket(size=4)

    contacts = [
        make_contact(1),
        make_contact(2),
        make_contact(3),
        make_contact(4),
    ]

    for contact in contacts:
        result = bucket.add(contact)

        assert result is None

    new_contact = make_contact(5)

    old_contact = bucket.add(
        new_contact
    )

    assert old_contact is not None

    assert (
        old_contact.node_id
        == make_contact(1).node_id
    )

    # Новый контакт пока НЕ должен быть добавлен.
    node_ids = [
        contact.node_id
        for contact in bucket.get_contacts()
    ]

    assert make_contact(5).node_id not in node_ids

    assert len(bucket) == 4


def test_replace_dead_contact():

    bucket = KBucket(size=4)

    for value in [1, 2, 3, 4]:
        bucket.add(
            make_contact(value)
        )

    new_contact = make_contact(5)

    old_contact = bucket.add(
        new_contact
    )

    assert old_contact is not None

    bucket.replace(
        old_node_id=old_contact.node_id,
        new_contact=new_contact,
    )

    node_ids = [
        contact.node_id
        for contact in bucket.get_contacts()
    ]

    assert make_contact(1).node_id not in node_ids
    assert make_contact(5).node_id in node_ids

    assert len(bucket) == 4


if __name__ == "__main__":
    test_full_bucket_returns_oldest_contact()
    test_replace_dead_contact()

    print(
        "KBucket PING eviction policy: PASSED"
    )