import asyncio
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from relay_server import RelayServer


async def start_destination():
    received = []

    async def handle_client(reader, writer):
        data = await reader.read(1024 * 1024)

        received.append(data)

        writer.write(b"ACK:" + data)
        await writer.drain()

        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        0,
    )

    port = server.sockets[0].getsockname()[1]

    return server, port, received


@pytest.mark.asyncio
async def test_relay_forwards_tcp_message():
    destination, destination_port, received = (
        await start_destination()
    )

    relay = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    relay_server = await relay.start()

    relay_port = relay_server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        relay_port,
    )

    writer.write(b"Hello through relay")
    await writer.drain()

    response = await reader.read(1024)

    writer.close()
    await writer.wait_closed()

    await relay.stop()

    destination.close()
    await destination.wait_closed()

    assert received == [b"Hello through relay"]
    assert response == b"ACK:Hello through relay"


@pytest.mark.asyncio
async def test_relay_forwards_binary_data():
    destination, destination_port, received = (
        await start_destination()
    )

    relay = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    relay_server = await relay.start()
    relay_port = relay_server.sockets[0].getsockname()[1]

    payload = bytes(range(256))

    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        relay_port,
    )

    writer.write(payload)
    await writer.drain()

    response = await reader.read(1024)

    writer.close()
    await writer.wait_closed()

    await relay.stop()

    destination.close()
    await destination.wait_closed()

    assert received == [payload]
    assert response == b"ACK:" + payload