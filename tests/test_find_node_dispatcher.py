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


def make_node_id(value: int) -> str:
    return f"{value:064x}"


def make_contact(value: int) -> Contact:
    return Contact(
        node_id=make_node_id(value),
        host="127.0.0.1",
        port=9000 + value,
    )


async def test_find_node():
    local_node_id = make_node_id(0)

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    for value in [1, 2, 4, 8, 16]:
        routing_table.add_contact(
            make_contact(value)
        )

    dispatcher = Dispatcher(
        routing_table=routing_table
    )

    request = FindNodeRequest(
        target_node_id=make_node_id(3)
    )

    frame = Frame(
        message_type=MessageType.FIND_NODE_REQUEST,
        payload=request.encode(),
    )

    response_frame = await dispatcher.dispatch(
        frame
    )

    assert (
        response_frame.message_type
        == MessageType.FIND_NODE_RESPONSE
    )

    print("FIND_NODE response type: PASS")

    response = FindNodeResponse.decode(
        response_frame.payload
    )

    values = [
        int(contact.node_id, 16)
        for contact in response.contacts
    ]

    expected = [2, 1, 4, 8, 16][:K_BUCKET_SIZE]
    assert values == expected

    print("FIND_NODE closest nodes: PASS")

    assert (
        response_frame.request_id
        == frame.request_id
    )

    print("Request ID preserved: PASS")


def main():
    asyncio.run(
        test_find_node()
    )

    print("\nFIND NODE DISPATCHER TEST PASSED")


if __name__ == "__main__":
    main()