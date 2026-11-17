import sys
from pathlib import Path
import time

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from dht_messages import NodeRecord
from dht_storage import DHTStorage
from identity import Identity


def test_unexpired_record_is_accepted(tmp_path):
    identity = Identity(
        tmp_path / "node"
    )

    now = int(time.time())

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9001"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
    )

    storage = DHTStorage()

    storage.store(record)

    stored = storage.get(
        identity.node_id
    )

    assert stored is not None
    assert stored.node_id == identity.node_id


def test_expired_record_is_rejected(tmp_path):
    identity = Identity(
        tmp_path / "node"
    )

    now = int(time.time())

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9001"],
        sequence_number=1,
        issued_at=now - 600,
        expires_at=now - 300,
    )

    storage = DHTStorage()

    with pytest.raises(
        ValueError,
        match="NodeRecord has expired",
    ):
        storage.store(record)

    assert storage.get(
        identity.node_id
    ) is None