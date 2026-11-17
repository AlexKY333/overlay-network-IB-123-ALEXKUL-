import sys
from pathlib import Path
import asyncio
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
from transport import Connection


async def start_node(
    node_id: str,
    storage: DHTStorage,
):
    routing_table = RoutingTable(
        local_node_id=node_id
    )

    dispatcher = Dispatcher(
        routing_table=routing_table,
        storage=storage,
    )

    async def handle_client(reader, writer):
        connection = Connection(
            reader,
            writer,
        )

        try:
            frame = await connection.receive_frame(
                timeout=5.0
            )

            response = await dispatcher.dispatch(
                frame
            )

            await connection.send_frame(
                response
            )

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        0,
    )

    port = server.sockets[0].getsockname()[1]

    return server, port


def make_record(node_id: str) -> NodeRecord:
    now = int(time.time())

    return NodeRecord(
        node_id=node_id,
        identity_public_key="public-key",
        addresses=["127.0.0.1:9001"],
        sequence_number=1,
        issued_at=now,
        expires_at=now + 300,
        signature="signature",
    )


@pytest.mark.asyncio
async def test_find_value_over_tcp_returns_stored_record():
    # -------------------------------------------------
    # Node B
    # -------------------------------------------------

    node_b_id = "b" * 64
    record_node_id = "a" * 64

    storage_b = DHTStorage()

    record = make_record(
        record_node_id
    )

    storage_b.store(record)

    server_b, port_b = await start_node(
        node_b_id,
        storage_b,
    )

    try:
        # -------------------------------------------------
        # Node A -> Node B
        # -------------------------------------------------

        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port_b,
        )

        connection = Connection(
            reader,
            writer,
        )

        request = FindValueRequest(
            node_id=record_node_id
        )

        frame = Frame(
            message_type=MessageType.FIND_VALUE_REQUEST,
            payload=request.encode(),
        )

        await connection.send_frame(
            frame
        )

        # -------------------------------------------------
        # Node B -> Node A
        # -------------------------------------------------

        response_frame = await connection.receive_frame(
            timeout=5.0
        )

        await connection.close()

        # -------------------------------------------------
        # Проверяем ответ
        # -------------------------------------------------

        assert (
            response_frame.message_type
            == MessageType.FIND_VALUE_RESPONSE
        )

        assert (
            response_frame.request_id
            == frame.request_id
        )

        response = FindValueResponse.decode(
            response_frame.payload
        )

        assert response.record == record
        assert response.contacts == []

    finally:
        server_b.close()
        await server_b.wait_closed()


@pytest.mark.asyncio
async def test_find_value_over_tcp_returns_closest_contacts():
    # -------------------------------------------------
    # Node B
    # -------------------------------------------------

    node_b_id = "b" * 64
    target_node_id = "a" * 64

    storage_b = DHTStorage()

    routing_table_b = RoutingTable(
        local_node_id=node_b_id
    )

    # Два контакта Node B.
    # Контакт A ближе к target_node_id, чем контакт C.
    close_contact = Contact(
        node_id="a" * 64,
        host="127.0.0.1",
        port=9001,
    )

    far_contact = Contact(
        node_id="f" * 64,
        host="127.0.0.1",
        port=9002,
    )

    routing_table_b.add_contact(
        close_contact
    )

    routing_table_b.add_contact(
        far_contact
    )

    dispatcher = Dispatcher(
        routing_table=routing_table_b,
        storage=storage_b,
    )

    async def handle_client(reader, writer):
        connection = Connection(
            reader,
            writer,
        )

        try:
            frame = await connection.receive_frame(
                timeout=5.0
            )

            response = await dispatcher.dispatch(
                frame
            )

            await connection.send_frame(
                response
            )

        finally:
            await connection.close()

    server_b = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        0,
    )

    port_b = server_b.sockets[0].getsockname()[1]

    try:
        # -------------------------------------------------
        # Node A -> Node B
        # -------------------------------------------------

        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port_b,
        )

        connection = Connection(
            reader,
            writer,
        )

        request = FindValueRequest(
            node_id=target_node_id
        )

        frame = Frame(
            message_type=MessageType.FIND_VALUE_REQUEST,
            payload=request.encode(),
        )

        await connection.send_frame(
            frame
        )

        # -------------------------------------------------
        # Node B -> Node A
        # -------------------------------------------------

        response_frame = await connection.receive_frame(
            timeout=5.0
        )

        await connection.close()

        # -------------------------------------------------
        # Проверяем ответ
        # -------------------------------------------------

        assert (
            response_frame.message_type
            == MessageType.FIND_VALUE_RESPONSE
        )

        assert (
            response_frame.request_id
            == frame.request_id
        )

        response = FindValueResponse.decode(
            response_frame.payload
        )

        # Записи нет
        assert response.record is None

        # Но Node B вернул ближайшие контакты
        assert len(response.contacts) == 2

        assert (
            response.contacts[0].node_id
            == close_contact.node_id
        )

        assert (
            response.contacts[1].node_id
            == far_contact.node_id
        )

    finally:
        server_b.close()
        await server_b.wait_closed()