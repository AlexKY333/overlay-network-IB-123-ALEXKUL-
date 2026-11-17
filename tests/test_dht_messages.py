import sys
from pathlib import Path
import sys
from pathlib import Path

SRC_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from contact import Contact
from dht_messages import (
    NodeRecord,
    FindNodeRequest,
    FindNodeResponse,
    StoreRequest,
    StoreResponse,
    FindValueRequest,
    FindValueResponse,
)
from identity import Identity


def test_dht_messages():
    target = (
        "1234567890abcdef"
        "1234567890abcdef"
        "1234567890abcdef"
        "1234567890abcdef"
    )

    # -----------------------------
    # FIND_NODE request
    # -----------------------------

    request = FindNodeRequest(
        target_node_id=target
    )

    encoded = request.encode()

    decoded = FindNodeRequest.decode(
        encoded
    )

    assert decoded.target_node_id == target

    print("FIND_NODE request: PASS")

    # -----------------------------
    # FIND_NODE response
    # -----------------------------

    node_ids = [
        target,
        (
            "abcdefabcdefabcdefabcdefabcdefab"
            "cdefabcdefabcdefabcdefabcdefabcd"
        ),
    ]

    contacts = [
        Contact(
            node_id=node_ids[0],
            host="127.0.0.1",
            port=9001
        ),
        Contact(
            node_id=node_ids[1],
            host="127.0.0.1",
            port=9002
        ),
    ]

    response = FindNodeResponse(
        contacts=contacts
    )

    encoded = response.encode()

    decoded = FindNodeResponse.decode(
        encoded
    )

    assert [contact.node_id for contact in decoded.contacts] == node_ids
    assert decoded.contacts[0].host == "127.0.0.1"
    assert decoded.contacts[0].port == 9001
    assert decoded.contacts[1].host == "127.0.0.1"
    assert decoded.contacts[1].port == 9002

    print("FIND_NODE response: PASS")

    # -----------------------------
    # Неверный NodeID
    # -----------------------------

    try:
        FindNodeRequest.decode(
            b"123"
        )

    except ValueError:
        print("Invalid NodeID rejected: PASS")

    else:
        raise AssertionError(
            "Invalid NodeID was accepted"
        )

    print("\nDHT MESSAGES TEST PASSED")

def test_alias_normalization():
    assert NodeRecord.normalize_alias(
        " Alice "
    ) == "alice"

    assert NodeRecord.normalize_alias(
        "ALICE"
    ) == "alice"

    assert NodeRecord.normalize_alias(
        "  Alice  "
    ) == "alice"

def test_alias_key_is_deterministic():
    key1 = NodeRecord.alias_key(
        "Alice"
    )

    key2 = NodeRecord.alias_key(
        " alice "
    )

    key3 = NodeRecord.alias_key(
        "ALICE"
    )

    assert key1 == key2
    assert key2 == key3

    assert len(key1) == 64

def test_alias_is_signed(tmp_path):
    identity = Identity(
        tmp_path
    )

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=100,
        expires_at=200,
        alias="Alice",
    )

    assert record.alias == "alice"
    assert record.verify_signature()

    record.alias = "bob"

    assert not record.verify_signature()


if __name__ == "__main__":
    test_dht_messages()

