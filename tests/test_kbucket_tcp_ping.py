import asyncio
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from config import K_BUCKET_SIZE
from contact import Contact
from dispatcher import Dispatcher
from routing_table import RoutingTable


def make_node_id(number: int) -> str:
    return f"{number:064x}"


async def start_ping_node(node_id: str):
    routing_table = RoutingTable(
        local_node_id=node_id
    )

    dispatcher = Dispatcher(
        routing_table=routing_table
    )

    async def handle_client(reader, writer):
        from transport import Connection

        connection = Connection(
            reader,
            writer
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

        except Exception:
            pass

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        host="127.0.0.1",
        port=0
    )

    port = server.sockets[0].getsockname()[1]

    return server, port


async def test_live_contact_survives_ping():
    """
    Если старый контакт отвечает на настоящий TCP PING,
    он должен остаться в bucket.
    """
    k = K_BUCKET_SIZE
    local_node_id = make_node_id(100)

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    old_contacts = []

    for number in range(1, k + 1):
        server, port = await start_ping_node(
            make_node_id(number)
        )
        old_contacts.append((server, port))

    try:
        for number, (server, port) in enumerate(old_contacts, start=1):
            contact = Contact(
                node_id=make_node_id(number),
                host="127.0.0.1",
                port=port
            )
            routing_table.add_contact(contact)

        new_contact = Contact(
            node_id=make_node_id(k + 1),
            host="127.0.0.1",
            port=9999
        )

        result = await routing_table.add_contact_with_ping(
            new_contact,
            timeout=1.0
        )

        contacts = routing_table.get_contacts()
        node_ids = [contact.node_id for contact in contacts]

        assert result is not None
        assert make_node_id(1) in node_ids
        assert make_node_id(k + 1) not in node_ids
        assert len(contacts) == k

    finally:
        for server, _ in old_contacts:
            server.close()
            await server.wait_closed()

    print("\nLIVE CONTACT -> PING -> PONG -> OLD CONTACT KEPT: PASSED")


async def test_live_contact_updates_last_seen():
    k = K_BUCKET_SIZE
    local_node_id = make_node_id(100)

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    old_contacts = []

    for number in range(1, k + 1):
        server, port = await start_ping_node(
            make_node_id(number)
        )
        old_contacts.append((server, port))

    try:
        for number, (server, port) in enumerate(old_contacts, start=1):
            contact = Contact(
                node_id=make_node_id(number),
                host="127.0.0.1",
                port=port
            )
            routing_table.add_contact(contact)

        old_contact = routing_table.get_contacts()[0]
        assert old_contact.last_seen is None

        new_contact = Contact(
            node_id=make_node_id(k + 1),
            host="127.0.0.1",
            port=9999
        )

        result = await routing_table.add_contact_with_ping(
            new_contact,
            timeout=1.0
        )

        assert result is old_contact
        assert old_contact.last_seen is not None
        assert old_contact.last_seen.tzinfo is not None

        node_ids = [
            contact.node_id
            for contact in routing_table.get_contacts()
        ]

        assert make_node_id(k + 1) not in node_ids
        assert len(node_ids) == k

    finally:
        for server, _ in old_contacts:
            server.close()
            await server.wait_closed()

    print("\nLIVE CONTACT -> PING -> last_seen UPDATED: PASSED")


async def test_dead_contact_is_replaced():
    """
    Если старый контакт не отвечает на TCP PING,
    он должен быть удалён, а новый контакт добавлен.
    """
    k = K_BUCKET_SIZE
    local_node_id = make_node_id(100)

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    for number in range(1, k + 1):
        contact = Contact(
            node_id=make_node_id(number),
            host="127.0.0.1",
            port=9999
        )
        routing_table.add_contact(contact)

    new_contact = Contact(
        node_id=make_node_id(k + 1),
        host="127.0.0.1",
        port=9998
    )

    result = await routing_table.add_contact_with_ping(
        new_contact,
        timeout=0.2
    )

    contacts = routing_table.get_contacts()
    node_ids = [contact.node_id for contact in contacts]

    assert result is None
    assert make_node_id(1) not in node_ids
    assert make_node_id(k + 1) in node_ids
    assert len(contacts) == k

    print("\nDEAD CONTACT -> PING TIMEOUT -> NEW CONTACT ADDED: PASSED")


if __name__ == "__main__":
    asyncio.run(test_live_contact_survives_ping())
    asyncio.run(test_dead_contact_is_replaced())
    asyncio.run(test_live_contact_updates_last_seen())