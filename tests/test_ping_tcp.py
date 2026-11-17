import asyncio
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from dispatcher import Dispatcher
from message_types import MessageType
from protocol import Frame
from routing_table import RoutingTable
from transport import Connection


async def test_ping_over_tcp():
    # Node B
    node_b_id = "b" * 64

    routing_table = RoutingTable(
        local_node_id=node_b_id
    )

    dispatcher = Dispatcher(
        routing_table=routing_table
    )

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)

        try:
            frame = await connection.receive_frame(
                timeout=5.0
            )

            response = await dispatcher.dispatch(frame)

            await connection.send_frame(response)

        finally:
            await connection.close()

    # Запускаем Node B на свободном TCP-порту
    server = await asyncio.start_server(
        handle_client,
        host="127.0.0.1",
        port=0
    )

    port = server.sockets[0].getsockname()[1]

    async with server:

        # Node A подключается к Node B
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            port
        )

        connection = Connection(reader, writer)

        # Node A формирует PING
        ping = Frame(
            message_type=MessageType.PING,
            payload=b"Hello from Node A!"
        )

        # Node A -> Node B
        await connection.send_frame(ping)

        # Node A получает ответ
        response = await connection.receive_frame(
            timeout=5.0
        )

        # Проверяем PONG
        assert response.message_type == MessageType.PONG

        # Payload должен вернуться без изменений
        assert response.payload == b"Hello from Node A!"

        # request_id должен сохраниться
        assert response.request_id == ping.request_id

        await connection.close()

    print("\nREAL TCP PING -> PONG TEST PASSED")


if __name__ == "__main__":
    asyncio.run(test_ping_over_tcp())