from pathlib import Path
import sys
import asyncio

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from dispatcher import Dispatcher
from protocol import Frame
from message_types import MessageType
from routing_table import RoutingTable


def make_node_id(value: int) -> str:
    return f"{value:064x}"


async def test_dispatcher():

    # -----------------------------------
    # Создаём routing table
    # -----------------------------------

    local_node_id = make_node_id(1)

    routing_table = RoutingTable(
        local_node_id=local_node_id
    )

    dispatcher = Dispatcher(
        routing_table=routing_table
    )

    # -----------------------------------
    # 1. PING → PONG
    # -----------------------------------

    ping = Frame(
        message_type=MessageType.PING,
        payload=b"Hello dispatcher!",
    )

    response = await dispatcher.dispatch(ping)

    print("TEST 1:")
    print(
        "PING ->",
        MessageType(response.message_type).name
    )
    print("Payload:", response.payload)

    assert response.message_type == MessageType.PONG
    assert response.payload == b"Hello dispatcher!"
    assert response.request_id == ping.request_id

    # -----------------------------------
    # 2. Неизвестный тип → ERROR
    # -----------------------------------

    unknown = Frame(
        message_type=255,
        payload=b"Unknown command",
    )

    response = await dispatcher.dispatch(unknown)

    print("\nTEST 2:")
    print(
        "255 ->",
        MessageType(response.message_type).name
    )
    print("Payload:", response.payload)

    assert response.message_type == MessageType.ERROR
    assert response.request_id == unknown.request_id

    # -----------------------------------
    # 3. FIND_NODE_REQUEST
    # -----------------------------------

    target_node_id = make_node_id(100)

    find_node_payload = (
        target_node_id.encode("ascii")
    )

    find_node = Frame(
        message_type=MessageType.FIND_NODE_REQUEST,
        payload=find_node_payload,
    )

    response = await dispatcher.dispatch(
        find_node
    )

    print("\nTEST 3:")
    print(
        "FIND_NODE_REQUEST ->",
        MessageType(response.message_type).name
    )
    print("Payload:", response.payload)

    assert (
        response.message_type
        == MessageType.FIND_NODE_RESPONSE
    )

    assert (
        response.request_id
        == find_node.request_id
    )

    print("\nDISPATCHER TEST PASSED")


asyncio.run(test_dispatcher())