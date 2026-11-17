import sys
import time
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from dht_messages import NodeRecord
from dht_storage import DHTStorage
from identity import Identity
from republisher import DHTRepublisher


def create_record(
    identity: Identity,
    issued_at: int,
    expires_at: int,
) -> NodeRecord:
    return NodeRecord.create_signed(
        identity=identity,
        addresses=[
            "127.0.0.1:9000"
        ],
        sequence_number=7,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def test_should_republish_at_half_ttl(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    now = int(time.time())

    record = create_record(
        identity=identity,
        issued_at=now,
        expires_at=now + 300,
    )

    storage.store(record)

    republisher = DHTRepublisher(
        identity=identity,
        storage=storage,
    )

    # TTL = 300 секунд.
    #
    # В этот момент осталось 151 секунда.
    assert (
        republisher.should_republish(
            identity.node_id,
            now=now + 149,
        )
        is False
    )

    # Осталось ровно 150 секунд = TTL / 2.
    assert (
        republisher.should_republish(
            identity.node_id,
            now=now + 150,
        )
        is True
    )


def test_republish_refreshes_ttl_and_signature(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    now = int(time.time())

    original = create_record(
        identity=identity,
        issued_at=now,
        expires_at=now + 300,
    )

    storage.store(original)

    republisher = DHTRepublisher(
        identity=identity,
        storage=storage,
    )

    refresh_time = now + 150

    refreshed = republisher.republish(
        node_id=identity.node_id,
        now=refresh_time,
    )

    # NodeID сохраняется.
    assert (
        refreshed.node_id
        == original.node_id
    )

    # Адреса сохраняются.
    assert (
        refreshed.addresses
        == original.addresses
    )

    # Sequence number сохраняется.
    assert (
        refreshed.sequence_number
        == original.sequence_number
    )

    # issued_at обновлён.
    assert (
        refreshed.issued_at
        == refresh_time
    )

    # TTL остался 300 секунд.
    assert (
        refreshed.expires_at
        == refresh_time + 300
    )

    # Новая подпись корректна.
    assert refreshed.verify_signature()

    # Поскольку signed-поля изменились,
    # подпись тоже должна измениться.
    assert (
        refreshed.signature
        != original.signature
    )

    # Storage содержит обновлённую запись.
    stored = storage.get(
        identity.node_id
    )

    assert stored is refreshed


def test_republish_due_records(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    now = int(time.time())

    record = create_record(
        identity=identity,
        issued_at=now,
        expires_at=now + 300,
    )

    storage.store(record)

    republisher = DHTRepublisher(
        identity=identity,
        storage=storage,
    )

    refresh_time = now + 150

    refreshed = (
        republisher.republish_due_records(
            now=refresh_time,
        )
    )

    assert len(refreshed) == 1

    assert (
        refreshed[0].issued_at
        == refresh_time
    )

    assert (
        refreshed[0].expires_at
        == refresh_time + 300
    )

    assert (
        refreshed[0].sequence_number
        == 7
    )

    assert (
        refreshed[0].verify_signature()
        is True
    )