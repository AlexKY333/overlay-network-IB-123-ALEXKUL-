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
from dispatcher import Dispatcher
from identity import Identity
from routing_table import RoutingTable
from refresh import DHTRefreshService


async def start_test_server(dispatcher):
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


def get_free_contact(
    identity,
    port,
):
    return Contact(
        node_id=identity.node_id,
        host="127.0.0.1",
        port=port,
    )


@pytest.mark.asyncio
async def test_refresh_discovers_new_contacts(
    tmp_path,
):
    local_identity = Identity(
        tmp_path / "local"
    )

    remote_identity = Identity(
        tmp_path / "remote"
    )

    discovered_identity = Identity(
        tmp_path / "discovered"
    )

    remote_routing = RoutingTable(
        remote_identity.node_id
    )

    discovered_contact = Contact(
        node_id=discovered_identity.node_id,
        host="127.0.0.1",
        port=9999,
    )

    remote_routing.add_contact(
        discovered_contact
    )

    dispatcher = Dispatcher(
        routing_table=remote_routing
    )

    server = await start_test_server(
        dispatcher
    )

    port = (
        server.sockets[0].getsockname()[1]
    )

    try:
        local_routing = RoutingTable(
            local_identity.node_id
        )

        remote_contact = get_free_contact(
            remote_identity,
            port,
        )

        local_routing.add_contact(
            remote_contact
        )

        service = DHTRefreshService(
            routing_table=local_routing,
        )

        discovered = await service.refresh_once()

        assert discovered >= 1

        node_ids = {
            contact.node_id
            for contact
            in local_routing.get_contacts()
        }

        assert (
            discovered_identity.node_id
            in node_ids
        )

    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_refresh_handles_dead_contact(
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

    dead_contact = Contact(
        node_id=dead_identity.node_id,
        host="127.0.0.1",
        port=65530,
    )

    routing_table.add_contact(
        dead_contact
    )

    service = DHTRefreshService(
        routing_table=routing_table,
    )

    discovered = await service.refresh_once(
        timeout=0.1
    )

    assert discovered == 0


def test_refresh_interval_validation(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    routing_table = RoutingTable(
        identity.node_id
    )

    with pytest.raises(ValueError):
        DHTRefreshService(
            routing_table=routing_table,
            interval=0,
        )

    with pytest.raises(ValueError):
        DHTRefreshService(
            routing_table=routing_table,
            interval=-1,
        )


@pytest.mark.asyncio
async def test_refresh_service_start_stop(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    routing_table = RoutingTable(
        identity.node_id
    )

    service = DHTRefreshService(
        routing_table=routing_table,
        interval=0.01,
    )

    assert service.running is False

    service.start()

    await asyncio.sleep(0.03)

    assert service.running is True

    await service.stop()

    assert service.running is False