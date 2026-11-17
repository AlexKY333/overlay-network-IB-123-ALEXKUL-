import sys
import time
from pathlib import Path

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
from replication import DHTReplicator


def create_record(identity: Identity) -> NodeRecord:
    now = int(time.time())

    return NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
    )


@pytest.mark.asyncio
async def test_replication_factor_validation(tmp_path):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    from routing_table import RoutingTable

    routing_table = RoutingTable(
        identity.node_id
    )

    with pytest.raises(ValueError):
        DHTReplicator(
            routing_table=routing_table,
            storage=storage,
            replication_factor=0,
        )

    with pytest.raises(ValueError):
        DHTReplicator(
            routing_table=routing_table,
            storage=storage,
            replication_factor=3,
            quorum=4,
        )


@pytest.mark.asyncio
async def test_local_replication_without_remote_nodes(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    from routing_table import RoutingTable

    routing_table = RoutingTable(
        identity.node_id
    )

    replicator = DHTReplicator(
        routing_table=routing_table,
        storage=storage,
        replication_factor=1,
        quorum=1,
    )

    record = create_record(identity)

    replicas = await replicator.replicate(
        record
    )

    assert replicas == 1

    stored = storage.get(
        identity.node_id
    )

    assert stored is not None
    assert stored.sequence_number == 1