from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from config import K_BUCKET_SIZE
from contact import Contact
from kbucket import KBucket


def make_contact(number: int) -> Contact:
    return Contact(
        node_id=f"{number:064x}",
        host="127.0.0.1",
        port=9000 + number,
    )


def test_kbucket():
    bucket = KBucket()
    k = K_BUCKET_SIZE

    # -----------------------------
    # 1. Заполняем bucket до K_BUCKET_SIZE
    # -----------------------------
    for number in range(1, k + 1):
        result = bucket.add(make_contact(number))
        assert result is None

    assert len(bucket) == k
    print(f"Bucket size {k}: PASS")

    # -----------------------------
    # 2. Проверяем порядок
    # -----------------------------
    contacts = bucket.get_contacts()
    for idx, number in enumerate(range(1, k + 1)):
        assert contacts[idx].port == 9000 + number

    print("Contact order: PASS")

    # -----------------------------
    # 3. Добавляем (k + 1)-й контакт в полный bucket
    # -----------------------------
    extra_num = k + 1
    old_contact = bucket.add(make_contact(extra_num))

    assert old_contact is not None
    assert old_contact.port == 9001
    assert len(bucket) == k

    contacts = bucket.get_contacts()
    assert all(
        contact.port != 9000 + extra_num
        for contact in contacts
    )

    print("Full bucket returns oldest contact: PASS")
    print("New contact waits for PING decision: PASS")

    # -----------------------------
    # 4. Повторно добавляем существующий контакт
    # -----------------------------
    existing_num = min(2, k)
    result = bucket.add(make_contact(existing_num))

    assert result is None
    contacts = bucket.get_contacts()
    assert contacts[-1].port == 9000 + existing_num
    assert len(bucket) == k

    print("Existing contact moves to end: PASS")

    # -----------------------------
    # 5. Удаляем контакт
    # -----------------------------
    bucket.remove(f"{k:064x}")

    assert len(bucket) == k - 1
    for contact in bucket.get_contacts():
        assert contact.port != 9000 + k

    print("Remove contact: PASS")
    print("\nKBUCKET TEST PASSED")


if __name__ == "__main__":
    test_kbucket()