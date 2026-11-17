import asyncio
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

from contact import Contact
from dht_messages import (
    FindValueRequest,
    FindValueResponse,
    NodeRecord,
)
from dht_storage import DHTStorage
from dispatcher import Dispatcher
from identity import Identity
from message_types import MessageType
from replication import DHTReplicator
from routing_table import RoutingTable
from protocol import Frame
from transport import Connection


async def start_test_server(
    dispatcher,
    host="127.0.0.1",
):
    async def handle_client(
        reader,
        writer,
    ):
        connection = Connection(
            reader,
            writer,
        )

        try:
            while True:
                frame = await connection.receive_frame(
                    timeout=5.0,
                )

                response = await dispatcher.dispatch(
                    frame
                )

                await connection.send_frame(
                    response
                )

        except (
            asyncio.IncompleteReadError,
            asyncio.TimeoutError,
            ConnectionError,
        ):
            pass

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        host,
        0,
    )

    return server


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
async def test_find_value_survives_one_replica_failure(
    tmp_path,
):
    # --------------------------------------------------
    # Создаём три узла
    # --------------------------------------------------

    identity_a = Identity(
        tmp_path / "node_a"
    )

    identity_b = Identity(
        tmp_path / "node_b"
    )

    identity_c = Identity(
        tmp_path / "node_c"
    )

    storage_a = DHTStorage()
    storage_b = DHTStorage()
    storage_c = DHTStorage()

    routing_a = RoutingTable(
        local_node_id=identity_a.node_id
    )

    routing_b = RoutingTable(
        local_node_id=identity_b.node_id
    )

    routing_c = RoutingTable(
        local_node_id=identity_c.node_id
    )

    dispatcher_b = Dispatcher(
        routing_table=routing_b,
        storage=storage_b,
    )

    dispatcher_c = Dispatcher(
        routing_table=routing_c,
        storage=storage_c,
    )

    # --------------------------------------------------
    # Запускаем B и C
    # --------------------------------------------------

    server_b = await start_test_server(
        dispatcher_b
    )

    server_c = await start_test_server(
        dispatcher_c
    )

    try:
        port_b = (
            server_b.sockets[0]
            .getsockname()[1]
        )

        port_c = (
            server_c.sockets[0]
            .getsockname()[1]
        )

        contact_b = Contact(
            node_id=identity_b.node_id,
            host="127.0.0.1",
            port=port_b,
        )

        contact_c = Contact(
            node_id=identity_c.node_id,
            host="127.0.0.1",
            port=port_c,
        )

        routing_a.add_contact(
            contact_b
        )

        routing_a.add_contact(
            contact_c
        )

        # --------------------------------------------------
        # Репликация R=3
        # --------------------------------------------------

        replicator = DHTReplicator(
            routing_table=routing_a,
            storage=storage_a,
            replication_factor=3,
            quorum=2,
        )

        record = create_record(
            identity_a
        )

        replicas = await replicator.replicate(
            record,
            timeout=2.0,
        )

        assert replicas == 3

        # Проверяем, что запись действительно есть
        # на всех трёх узлах.
        assert storage_a.get(
            identity_a.node_id
        ) is not None

        assert storage_b.get(
            identity_a.node_id
        ) is not None

        assert storage_c.get(
            identity_a.node_id
        ) is not None

        # --------------------------------------------------
        # Имитируем отказ Node C
        # --------------------------------------------------

        server_c.close()

        await server_c.wait_closed()

        # --------------------------------------------------
        # FIND_VALUE через оставшуюся реплику B
        # --------------------------------------------------

        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port_b,
        )

        connection = Connection(
            reader,
            writer,
        )

        try:
            request = FindValueRequest(
                node_id=identity_a.node_id
            )

            frame = Frame(
                message_type=MessageType.FIND_VALUE_REQUEST,
                payload=request.encode(),
            )

            await connection.send_frame(
                frame
            )

            response_frame = (
                await connection.receive_frame(
                    timeout=2.0
                )
            )

            assert (
                response_frame.message_type
                == MessageType.FIND_VALUE_RESPONSE
            )

            response = FindValueResponse.decode(
                response_frame.payload
            )

            # --------------------------------------------------
            # Главная проверка:
            # оставшаяся реплика B отдаёт VALUE.
            # --------------------------------------------------

            assert response.record is not None

            assert (
                response.record.node_id
                == identity_a.node_id
            )

            assert (
                response.record.sequence_number
                == record.sequence_number
            )

            assert (
                response.record.signature
                == record.signature
            )

            assert response.record.verify_signature()

            assert response.contacts == []

        finally:
            await connection.close()

    finally:
        server_b.close()

        await server_b.wait_closed()