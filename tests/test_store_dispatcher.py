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


@pytest.mark.asyncio
async def test_store_request_is_saved_in_storage(
    tmp_path,
):
    identity = Identity(
        tmp_path / "node_a"
    )

    routing_table = RoutingTable(
        local_node_id=identity.node_id
    )

    storage = DHTStorage()

    dispatcher = Dispatcher(
        routing_table=routing_table,
        storage=storage,
    )

    now = int(time.time())

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9001"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
    )

    request = Frame(
        message_type=MessageType.STORE_REQUEST,
        payload=record.encode(),
    )

    response = await dispatcher.dispatch(
        request
    )

    assert response.message_type == MessageType.STORE_RESPONSE
    assert response.payload == b"OK"

    stored = storage.get(
        identity.node_id
    )

    assert stored is not None
    assert stored.node_id == identity.node_id
    assert stored.verify_signature()