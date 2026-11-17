import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import asyncio

import pytest

from contact import Contact
from dht_messages import FindNodeResponse
from dispatcher import Dispatcher
from identity import Identity
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from bootstrap import DHTBootstrapper


async def start_test_server(
    dispatcher,
):
    async def handle_client(
        reader,
        writer,
    ):
        from transport import Connection

        connection = Connection(
            reader,
            writer,
        )

        try:
            frame = await connection.receive_frame(
                timeout=2.0
            )

            response = await dispatcher.dispatch(
                frame
            )

            await connection.send_frame(
                response
            )

        finally:
            writer.close()

            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        0,
    )

    return server


@pytest.mark.asyncio
async def test_bootstrap_discovers_contacts(
    tmp_path,
):
    bootstrap_identity = Identity(
        tmp_path / "bootstrap"
    )

    discovered_identity = Identity(
        tmp_path / "discovered"
    )

    local_identity = Identity(
        tmp_path / "local"
    )

    bootstrap_routing = RoutingTable(
        bootstrap_identity.node_id
    )

    discovered_contact = Contact(
        node_id=discovered_identity.node_id,
        host="127.0.0.1",
        port=9999,
    )

    bootstrap_routing.add_contact(
        discovered_contact
    )

    dispatcher = Dispatcher(
        routing_table=bootstrap_routing
    )

    server = await start_test_server(
        dispatcher
    )

    bootstrap_port = (
        server.sockets[0].getsockname()[1]
    )

    try:
        local_routing = RoutingTable(
            local_identity.node_id
        )

        bootstrap_contact = Contact(
            node_id=bootstrap_identity.node_id,
            host="127.0.0.1",
            port=bootstrap_port,
        )

        bootstrapper = DHTBootstrapper(
            routing_table=local_routing
        )

        added = await bootstrapper.bootstrap(
            contacts=[
                bootstrap_contact
            ]
        )

        contacts = (
            local_routing.get_contacts()
        )

        node_ids = {
            contact.node_id
            for contact in contacts
        }

        assert (
            bootstrap_identity.node_id
            in node_ids
        )

        assert (
            discovered_identity.node_id
            in node_ids
        )

        assert added >= 1

    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_bootstrap_ignores_local_node(
    tmp_path,
):
    identity = Identity(
        tmp_path / "local"
    )

    routing_table = RoutingTable(
        identity.node_id
    )

    bootstrapper = DHTBootstrapper(
        routing_table=routing_table
    )

    local_contact = Contact(
        node_id=identity.node_id,
        host="127.0.0.1",
        port=9999,
    )

    added = await bootstrapper.bootstrap(
        contacts=[
            local_contact
        ]
    )

    assert added == 0
    assert (
        routing_table.get_contacts()
        == []
    )


@pytest.mark.asyncio
async def test_bootstrap_handles_dead_node(
    tmp_path,
):
    local_identity = Identity(
        tmp_path / "local"
    )

    dead_identity = Identity(
        tmp_path / "dead"
    )

    routing_table = RoutingTable(
        local_identity.node_id
    )

    bootstrapper = DHTBootstrapper(
        routing_table=routing_table
    )

    dead_contact = Contact(
        node_id=dead_identity.node_id,
        host="127.0.0.1",
        port=65530,
    )

    added = await bootstrapper.bootstrap(
        contacts=[
            dead_contact
        ],
        timeout=0.1,
    )

    # Сам bootstrap-контакт добавляется в таблицу,
    # даже если TCP-соединение не удалось.
    assert added == 0

    contacts = (
        routing_table.get_contacts()
    )

    assert len(contacts) == 1
    assert (
        contacts[0].node_id
        == dead_identity.node_id
    )