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


async def start_relay(next_port):
    relay = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=next_port,
    )

    server = await relay.start()

    port = server.sockets[0].getsockname()[1]

    return relay, port


@pytest.mark.asyncio
async def test_three_relay_tcp_chain():
    # Node B
    destination, destination_port, received = (
        await start_destination()
    )

    # Relay 3 -> Node B
    relay3, relay3_port = await start_relay(
        destination_port
    )

    # Relay 2 -> Relay 3
    relay2, relay2_port = await start_relay(
        relay3_port
    )

    # Relay 1 -> Relay 2
    relay1, relay1_port = await start_relay(
        relay2_port
    )

    # Node A -> Relay 1
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        relay1_port,
    )

    payload = b"Hello through 3 relays!"

    writer.write(payload)
    await writer.drain()

    response = await reader.read(1024)

    writer.close()
    await writer.wait_closed()

    # Проверяем конечный результат.
    assert received == [payload]
    assert response == b"ACK:" + payload

    # Проверяем, что сообщение прошло через КАЖДЫЙ relay.
    assert relay1.forwarded_messages == 1
    assert relay2.forwarded_messages == 1
    assert relay3.forwarded_messages == 1

    await relay1.stop()
    await relay2.stop()
    await relay3.stop()

    destination.close()
    await destination.wait_closed()


@pytest.mark.asyncio
async def test_three_relays_forward_multiple_messages():
    destination, destination_port, received = (
        await start_destination()
    )

    relay3, relay3_port = await start_relay(
        destination_port
    )

    relay2, relay2_port = await start_relay(
        relay3_port
    )

    relay1, relay1_port = await start_relay(
        relay2_port
    )

    messages = [
        b"message-1",
        b"message-2",
        b"message-3",
    ]

    for message in messages:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            relay1_port,
        )

        writer.write(message)
        await writer.drain()

        response = await reader.read(1024)

        writer.close()
        await writer.wait_closed()

        assert response == b"ACK:" + message

    assert received == messages

    assert relay1.forwarded_messages == 3
    assert relay2.forwarded_messages == 3
    assert relay3.forwarded_messages == 3

    await relay1.stop()
    await relay2.stop()
    await relay3.stop()

    destination.close()
    await destination.wait_closed()