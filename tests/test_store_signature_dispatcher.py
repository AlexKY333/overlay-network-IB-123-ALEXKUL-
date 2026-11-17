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
from dispatcher import Dispatcher
from identity import Identity
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable


def create_record(
    identity: Identity,
) -> NodeRecord:
    now = int(time.time())

    return NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
    )


@pytest.mark.asyncio
async def test_store_accepts_valid_signed_record(
    tmp_path,
):
    identity = Identity(
        tmp_path / "node_a"
    )

    storage = DHTStorage()

    dispatcher = Dispatcher(
        routing_table=RoutingTable(
            local_node_id=identity.node_id
        ),
        storage=storage,
    )

    record = create_record(
        identity
    )

    frame = Frame(
        message_type=MessageType.STORE_REQUEST,
        payload=record.encode(),
    )

    response = await dispatcher.dispatch(
        frame
    )

    assert response.message_type == MessageType.STORE_RESPONSE
    assert response.payload == b"OK"

    stored = storage.get(
        identity.node_id
    )

    assert stored is not None
    assert stored.verify_signature()


@pytest.mark.asyncio
async def test_store_rejects_modified_record(
    tmp_path,
):
    identity = Identity(
        tmp_path / "node_a"
    )

    storage = DHTStorage()

    dispatcher = Dispatcher(
        routing_table=RoutingTable(
            local_node_id=identity.node_id
        ),
        storage=storage,
    )

    record = create_record(
        identity
    )

    record.sequence_number = 2

    frame = Frame(
        message_type=MessageType.STORE_REQUEST,
        payload=record.encode(),
    )

    response = await dispatcher.dispatch(
        frame
    )

    assert response.message_type == MessageType.ERROR
    assert b"Invalid NodeRecord signature" in response.payload

    assert storage.get(
        identity.node_id
    ) is None


@pytest.mark.asyncio
async def test_store_rejects_wrong_node_id(
    tmp_path,
):
    identity = Identity(
        tmp_path / "node_a"
    )

    storage = DHTStorage()

    dispatcher = Dispatcher(
        routing_table=RoutingTable(
            local_node_id=identity.node_id
        ),
        storage=storage,
    )

    record = create_record(
        identity
    )

    record.node_id = "0" * 64

    frame = Frame(
        message_type=MessageType.STORE_REQUEST,
        payload=record.encode(),
    )

    response = await dispatcher.dispatch(
        frame
    )

    assert response.message_type == MessageType.ERROR

    assert storage.get(
        identity.node_id
    ) is None


@pytest.mark.asyncio
async def test_store_rejects_invalid_signature(
    tmp_path,
):
    identity = Identity(
        tmp_path / "node_a"
    )

    storage = DHTStorage()

    dispatcher = Dispatcher(
        routing_table=RoutingTable(
            local_node_id=identity.node_id
        ),
        storage=storage,
    )

    record = create_record(
        identity
    )

    record.signature = "invalid-signature"

    frame = Frame(
        message_type=MessageType.STORE_REQUEST,
        payload=record.encode(),
    )

    response = await dispatcher.dispatch(
        frame
    )

    assert response.message_type == MessageType.ERROR

    assert storage.get(
        identity.node_id
    ) is None