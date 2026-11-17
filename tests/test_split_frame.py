import asyncio

from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from protocol import Frame
from message_types import MessageType
from transport import Connection


async def test_split_frame():
    server_ready = asyncio.Event()

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)

        try:
            frame = await connection.receive_frame()

            print("SERVER:")
            print(
                "type:",
                MessageType(frame.message_type).name,
            )
            print(
                "payload:",
                frame.payload,
            )

            assert frame.message_type == MessageType.PING
            assert frame.payload == b"Hello split frame!"

            server_ready.set()

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        9002,
    )

    async with server:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            9002,
        )

        frame = Frame(
            message_type=MessageType.PING,
            payload=b"Hello split frame!",
        )

        data = frame.encode()

        # Намеренно разбиваем один кадр на несколько частей.
        part1 = data[:5]
        part2 = data[5:15]
        part3 = data[15:]

        print("CLIENT:")
        print("Отправляем кадр тремя частями...")

        writer.write(part1)
        await writer.drain()

        await asyncio.sleep(0.1)

        writer.write(part2)
        await writer.drain()

        await asyncio.sleep(0.1)

        writer.write(part3)
        await writer.drain()

        await asyncio.wait_for(
            server_ready.wait(),
            timeout=5,
        )

        writer.close()
        await writer.wait_closed()

    server.close()
    await server.wait_closed()

    print("SPLIT FRAME TEST PASSED")


asyncio.run(test_split_frame())