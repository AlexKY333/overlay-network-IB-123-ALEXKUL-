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
from tunnel import Tunnel


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
async def test_relay_server_uses_tunnel_next_hop():
    destination, destination_port, received = (
        await start_destination()
    )

    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.add_relay(2)
    tunnel.add_relay(3)
    tunnel.add_relay(4)

    tunnel.activate()

    node_addresses = {
        1: ("127.0.0.1", 9991),
        2: ("127.0.0.1", 9992),
        3: ("127.0.0.1", 9993),
        4: ("127.0.0.1", 9994),
        10: ("127.0.0.1", destination_port),
    }

    relay = RelayServer.from_tunnel(
        host="127.0.0.1",
        port=0,
        tunnel=tunnel,
        relay_node_id=4,
        node_addresses=node_addresses,
    )

    server = await relay.start()
    relay_port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        relay_port,
    )

    writer.write(b"Tunnel message")
    await writer.drain()

    response = await reader.read(1024)

    writer.close()
    await writer.wait_closed()

    await relay.stop()

    destination.close()
    await destination.wait_closed()

    assert received == [b"Tunnel message"]
    assert response == b"ACK:Tunnel message"

    assert relay.forwarded_messages == 1


@pytest.mark.asyncio
async def test_relay_server_rejects_unknown_next_hop():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.add_relay(2)
    tunnel.add_relay(3)
    tunnel.add_relay(4)

    tunnel.activate()

    node_addresses = {
        1: ("127.0.0.1", 9991),
        2: ("127.0.0.1", 9992),
        3: ("127.0.0.1", 9993),
        4: ("127.0.0.1", 9994),
        # Node 10 намеренно отсутствует.
    }

    with pytest.raises(ValueError):
        RelayServer.from_tunnel(
            host="127.0.0.1",
            port=0,
            tunnel=tunnel,
            relay_node_id=4,
            node_addresses=node_addresses,
        )


@pytest.mark.asyncio
async def test_relay_server_rejects_non_tunnel_relay():
    tunnel = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel.add_relay(2)
    tunnel.add_relay(3)
    tunnel.add_relay(4)

    tunnel.activate()

    node_addresses = {
        10: ("127.0.0.1", 9000),
    }

    with pytest.raises(ValueError):
        RelayServer.from_tunnel(
            host="127.0.0.1",
            port=0,
            tunnel=tunnel,
            relay_node_id=99,
            node_addresses=node_addresses,
        )