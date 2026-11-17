import asyncio
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from transport import Connection


async def test_timeout():
    server_ready = asyncio.Event()
    timeout_received = asyncio.Event()

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)

        server_ready.set()

        try:
            await connection.receive_frame(
                timeout=1.0
            )

        except asyncio.TimeoutError:
            print("Сервер: получен тайм-аут")
            timeout_received.set()

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        9004,
    )

    async with server:
        client_reader, client_writer = (
            await asyncio.open_connection(
                "127.0.0.1",
                9004,
            )
        )

        await server_ready.wait()

        # Ничего не отправляем.
        # Сервер должен дождаться кадра
        # и получить timeout.

        try:
            await asyncio.wait_for(
                timeout_received.wait(),
                timeout=2.0,
            )
        finally:
            client_writer.close()
            await client_writer.wait_closed()

    assert timeout_received.is_set()

    print("TIMEOUT TEST PASSED")


if __name__ == "__main__":
    asyncio.run(test_timeout())