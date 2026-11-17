from pathlib import Path
import sys
import asyncio

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from config import K_BUCKET_SIZE
from contact import Contact
from dispatcher import Dispatcher
from dht_messages import FindNodeRequest
from dht_messages import FindNodeResponse
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection


def make_node_id(value: int) -> str:
    return f"{value:064x}"


async def test_find_node_over_tcp():
    local_node_id = make_node_id(0)

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    for value in [1, 2, 4, 8, 16]:
        routing_table.add_contact(
            Contact(
                node_id=make_node_id(value),
                host="127.0.0.1",
                port=9000,
            )
        )

    dispatcher = Dispatcher(
        routing_table=routing_table
    )

    async def handle_client(reader, writer):
        connection = Connection(
            reader,
            writer,
        )

        try:
            frame = await connection.receive_frame()

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

    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port,
        )

        connection = Connection(
            reader,
            writer,
        )

        request = FindNodeRequest(
            target_node_id=make_node_id(3)
        )

        frame = Frame(
            message_type=MessageType.FIND_NODE_REQUEST,
            payload=request.encode(),
        )

        await connection.send_frame(frame)

        response_frame = await connection.receive_frame()

        assert (
            response_frame.message_type
            == MessageType.FIND_NODE_RESPONSE
        )

        assert (
            response_frame.request_id
            == frame.request_id
        )

        response = FindNodeResponse.decode(
            response_frame.payload
        )

        values = [
            int(contact.node_id, 16)
            for contact in response.contacts
        ]

        expected = [2, 1, 4, 8, 16][:K_BUCKET_SIZE]
        assert values == expected

        await connection.close()

    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(test_find_node_over_tcp())
    print("TCP FIND_NODE test: PASSED")