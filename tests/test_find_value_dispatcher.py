import sys
from pathlib import Path
import time

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from contact import Contact
from dht_messages import (
    FindValueRequest,
    FindValueResponse,
    NodeRecord,
)
from dht_storage import DHTStorage
from dispatcher import Dispatcher
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable


def make_record() -> NodeRecord:
    now = int(time.time())

    return NodeRecord(
        node_id="a" * 64,
        identity_public_key="public-key",
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
        signature="signature",
    )


@pytest.mark.asyncio
async def test_find_value_returns_stored_record():
    local_node_id = "b" * 64

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    storage = DHTStorage()

    record = make_record()

    storage.store(record)

    dispatcher = Dispatcher(
        routing_table=routing_table,
        storage=storage,
    )

    request = FindValueRequest(
        node_id=record.node_id
    )

    frame = Frame(
        message_type=MessageType.FIND_VALUE_REQUEST,
        payload=request.encode(),
    )

    response = await dispatcher.dispatch(frame)

    assert response.message_type == MessageType.FIND_VALUE_RESPONSE
    assert response.request_id == frame.request_id

    decoded_response = FindValueResponse.decode(
        response.payload
    )

    assert decoded_response.record == record
    assert decoded_response.contacts == []


@pytest.mark.asyncio
async def test_find_value_returns_contacts_when_record_missing():
    local_node_id = "b" * 64

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    storage = DHTStorage()

    dispatcher = Dispatcher(
        routing_table=routing_table,
        storage=storage,
    )

    target_node_id = "a" * 64

    request = FindValueRequest(
        node_id=target_node_id
    )

    frame = Frame(
        message_type=MessageType.FIND_VALUE_REQUEST,
        payload=request.encode(),
    )

    response = await dispatcher.dispatch(frame)

    assert response.message_type == MessageType.FIND_VALUE_RESPONSE
    assert response.request_id == frame.request_id

    decoded_response = FindValueResponse.decode(
        response.payload
    )

    assert decoded_response.record is None


@pytest.mark.asyncio
async def test_find_value_returns_closest_contacts_when_record_missing():
    local_node_id = "b" * 64

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    storage = DHTStorage()

    contacts = [
        Contact(
            node_id="a" * 64,
            host="127.0.0.1",
            port=9001,
        ),
        Contact(
            node_id="c" * 64,
            host="127.0.0.1",
            port=9002,
        ),
    ]

    for contact in contacts:
        routing_table.add_contact(contact)

    dispatcher = Dispatcher(
        routing_table=routing_table,
        storage=storage,
    )

    target_node_id = "a" * 64

    request = FindValueRequest(
        node_id=target_node_id
    )

    frame = Frame(
        message_type=MessageType.FIND_VALUE_REQUEST,
        payload=request.encode(),
    )

    response = await dispatcher.dispatch(frame)

    assert response.message_type == MessageType.FIND_VALUE_RESPONSE
    assert response.request_id == frame.request_id

    decoded_response = FindValueResponse.decode(
        response.payload
    )

    assert decoded_response.record is None
    assert decoded_response.contacts

    returned_node_ids = {
        contact.node_id
        for contact in decoded_response.contacts
    }

    assert "a" * 64 in returned_node_ids
    assert "c" * 64 in returned_node_ids