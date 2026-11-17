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


async def test_multiple_frames():
    server_ready = asyncio.Event()

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)

        try:
            frame1 = await connection.receive_frame()
            frame2 = await connection.receive_frame()
            frame3 = await connection.receive_frame()

            print("SERVER:")
            print("1:", MessageType(frame1.message_type).name, frame1.payload)
            print("2:", MessageType(frame2.message_type).name, frame2.payload)
            print("3:", MessageType(frame3.message_type).name, frame3.payload)

            assert frame1.message_type == MessageType.PING
            assert frame2.message_type == MessageType.PING
            assert frame3.message_type == MessageType.PING

            assert frame1.payload == b"first"
            assert frame2.payload == b"second"
            assert frame3.payload == b"third"

            server_ready.set()

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        9001,
    )

    async with server:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            9001,
        )

        frame1 = Frame(
            message_type=MessageType.PING,
            payload=b"first",
        )

        frame2 = Frame(
            message_type=MessageType.PING,
            payload=b"second",
        )

        frame3 = Frame(
            message_type=MessageType.PING,
            payload=b"third",
        )

        # Намеренно отправляем три кадра одним write.
        writer.write(
            frame1.encode()
            + frame2.encode()
            + frame3.encode()
        )

        await writer.drain()

        await asyncio.wait_for(
            server_ready.wait(),
            timeout=5,
        )

        writer.close()
        await writer.wait_closed()

    server.close()
    await server.wait_closed()

    print("MULTIPLE FRAMES TEST PASSED")


asyncio.run(test_multiple_frames())