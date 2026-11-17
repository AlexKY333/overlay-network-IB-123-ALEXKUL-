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


async def test_incomplete_frame():
    server_finished = asyncio.Event()

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)

        try:
            # Клиент намеренно закроет соединение
            # до отправки полного кадра.
            await connection.receive_frame()

        except asyncio.IncompleteReadError:
            print("SERVER:")
            print("Получен неполный кадр — соединение оборвано.")
            server_finished.set()

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        9003,
    )

    async with server:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            9003,
        )

        frame = Frame(
            message_type=MessageType.PING,
            payload=b"This frame is incomplete!",
        )

        data = frame.encode()

        # Отправляем только часть кадра.
        partial_data = data[:10]

        print("CLIENT:")
        print("Отправляем только часть кадра...")

        writer.write(partial_data)
        await writer.drain()

        # Сразу закрываем соединение.
        # Сервер не получит оставшуюся часть.
        writer.close()
        await writer.wait_closed()

        await asyncio.wait_for(
            server_finished.wait(),
            timeout=5,
        )

    server.close()
    await server.wait_closed()

    print("INCOMPLETE FRAME TEST PASSED")


asyncio.run(test_incomplete_frame())