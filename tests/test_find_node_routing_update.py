from pathlib import Path
import sys
import asyncio

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from contact import Contact
from routing_table import RoutingTable
from dht_messages import FindNodeRequest, FindNodeResponse
from dispatcher import Dispatcher
from protocol import Frame
from message_types import MessageType
from transport import Connection


async def dummy_server():
    server = await asyncio.start_server(
        lambda reader, writer: handle_dummy_client(
            reader,
            writer
        ),
        "127.0.0.1",
        0
    )

    return server


async def handle_dummy_client(
    reader,
    writer
):
    try:
        await reader.read(1024)
    finally:
        writer.close()
        await writer.wait_closed()


async def test_find_node_response_updates_routing_table():
    node_a_id = "a" * 64
    node_b_id = "b" * 64

    routing_b = RoutingTable(
        local_node_id=node_b_id
    )

    node_ids_b = [
        "1" * 64,
        "2" * 64,
        "3" * 64,
    ]

    servers = []

    contacts_b = []

    for node_id in node_ids_b:
        server = await dummy_server()

        servers.append(server)

        port = server.sockets[0].getsockname()[1]

        contact = Contact(
            node_id=node_id,
            host="127.0.0.1",
            port=port
        )

        contacts_b.append(contact)

        routing_b.add_contact(
            contact
        )

    dispatcher_b = Dispatcher(
        routing_b
    )

    request = FindNodeRequest(
        target_node_id=node_ids_b[1]
    )

    request_frame = Frame(
        message_type=MessageType.FIND_NODE_REQUEST,
        payload=request.encode()
    )

    response_frame = await dispatcher_b.dispatch(
        request_frame
    )

    assert (
        response_frame.message_type
        == MessageType.FIND_NODE_RESPONSE
    )

    find_node_response = FindNodeResponse.decode(
        response_frame.payload
    )

    assert len(
        find_node_response.contacts
    ) > 0

    returned_node_ids = [
        contact.node_id
        for contact in find_node_response.contacts
    ]

    assert node_ids_b[0] in returned_node_ids
    assert node_ids_b[1] in returned_node_ids
    assert node_ids_b[2] in returned_node_ids

    for contact in find_node_response.contacts:
        assert contact.host == "127.0.0.1"
        assert contact.port > 0

    routing_a = RoutingTable(
        local_node_id=node_a_id
    )

    for contact in find_node_response.contacts:
        routing_a.add_contact(
            contact
        )

    discovered_contacts = routing_a.get_contacts()

    discovered_node_ids = [
        contact.node_id
        for contact in discovered_contacts
    ]

    assert node_ids_b[0] in discovered_node_ids
    assert node_ids_b[1] in discovered_node_ids
    assert node_ids_b[2] in discovered_node_ids

    assert len(discovered_contacts) == 3

    for server in servers:
        server.close()
        await server.wait_closed()