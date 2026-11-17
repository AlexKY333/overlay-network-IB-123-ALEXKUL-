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
from dht_messages import NodeRecord
from dht_storage import DHTStorage
from dispatcher import Dispatcher
from identity import Identity
from replication import DHTReplicator
from routing_table import RoutingTable
from transport import Connection


async def start_test_server(
    dispatcher,
    host: str = "127.0.0.1",
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
async def test_store_is_replicated_to_three_nodes(
    tmp_path,
):
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

    server_b = await start_test_server(
        dispatcher_b
    )

    server_c = await start_test_server(
        dispatcher_c
    )

    try:
        port_b = server_b.sockets[0].getsockname()[1]
        port_c = server_c.sockets[0].getsockname()[1]

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

        assert storage_a.get(
            identity_a.node_id
        ) is not None

        assert storage_b.get(
            identity_a.node_id
        ) is not None

        assert storage_c.get(
            identity_a.node_id
        ) is not None

    finally:
        server_b.close()
        server_c.close()

        await server_b.wait_closed()
        await server_c.wait_closed()