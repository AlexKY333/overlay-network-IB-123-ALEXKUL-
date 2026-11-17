import sys
from pathlib import Path
import pytest
import time

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from dht_messages import NodeRecord, StoreRequest
from dht_storage import DHTStorage


def make_record(
    node_id: str,
    sequence_number: int,
) -> NodeRecord:
    now = int(time.time())

    return NodeRecord(
        node_id=node_id,
        identity_public_key="public-key",
        addresses=["127.0.0.1:9000"],
        sequence_number=sequence_number,
        issued_at=now,
        expires_at=now + 300,
        signature="signature",
    )


def test_store_and_get_record():
    storage = DHTStorage()

    record = make_record(
        "a" * 64,
        sequence_number=1,
    )

    storage.store(record)

    result = storage.get(record.node_id)

    assert result == record
    assert len(storage) == 1


def test_newer_record_replaces_old_record():
    storage = DHTStorage()

    old_record = make_record(
        "a" * 64,
        sequence_number=1,
    )

    new_record = make_record(
        "a" * 64,
        sequence_number=2,
    )

    storage.store(old_record)
    storage.store(new_record)

    result = storage.get(old_record.node_id)

    assert result == new_record


def test_sequence_number_rollback_is_rejected():
    storage = DHTStorage()

    new_record = make_record(
        "a" * 64,
        sequence_number=2,
    )

    old_record = make_record(
        "a" * 64,
        sequence_number=1,
    )

    storage.store(new_record)

    with pytest.raises(
        ValueError,
        match="Sequence number rollback",
    ):
        storage.store(old_record)


def test_delete_record():
    storage = DHTStorage()

    record = make_record(
        "a" * 64,
        sequence_number=1,
    )

    storage.store(record)

    storage.delete(record.node_id)

    assert storage.get(record.node_id) is None
    assert len(storage) == 0


def test_store_request_record_roundtrip():
    record = make_record(
        "a" * 64,
        sequence_number=1,
    )

    request = StoreRequest(
        record=record
    )

    decoded_request = StoreRequest.decode(
        request.encode()
    )

    assert decoded_request.record == record