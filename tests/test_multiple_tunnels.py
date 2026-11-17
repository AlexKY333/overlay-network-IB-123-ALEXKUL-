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


async def send_message(port, message):
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        port,
    )

    writer.write(message)
    await writer.drain()

    response = await reader.read(1024)

    writer.close()
    await writer.wait_closed()

    return response


@pytest.mark.asyncio
async def test_three_tunnels_active_simultaneously():
    destinations = []
    relays = []

    tunnels = [
        Tunnel(
            source_node_id=1,
            destination_node_id=10,
        ),
        Tunnel(
            source_node_id=20,
            destination_node_id=30,
        ),
        Tunnel(
            source_node_id=40,
            destination_node_id=50,
        ),
    ]

    for tunnel in tunnels:
        tunnel.add_relay(tunnel.source_node_id + 1)
        tunnel.add_relay(tunnel.source_node_id + 2)
        tunnel.add_relay(tunnel.source_node_id + 3)

        tunnel.activate()

    assert all(
        tunnel.is_active()
        for tunnel in tunnels
    )

    assert len({
        tunnel.tunnel_id
        for tunnel in tunnels
    }) == 3

    for tunnel in tunnels:
        destination, destination_port, received = (
            await start_destination()
        )

        destinations.append(
            (destination, received)
        )

        relay_node_id = tunnel.relay_node_ids[-1]

        node_addresses = {
            tunnel.destination_node_id: (
                "127.0.0.1",
                destination_port,
            )
        }

        relay = RelayServer.from_tunnel(
            host="127.0.0.1",
            port=0,
            tunnel=tunnel,
            relay_node_id=relay_node_id,
            node_addresses=node_addresses,
        )

        server = await relay.start()

        relay_port = server.sockets[0].getsockname()[1]

        relays.append(
            (relay, relay_port)
        )

    messages = [
        b"message-from-tunnel-1",
        b"message-from-tunnel-2",
        b"message-from-tunnel-3",
    ]

    responses = []

    for _, relay_port in relays:
        index = len(responses)

        response = await send_message(
            relay_port,
            messages[index],
        )

        responses.append(response)

    assert responses == [
        b"ACK:message-from-tunnel-1",
        b"ACK:message-from-tunnel-2",
        b"ACK:message-from-tunnel-3",
    ]

    assert destinations[0][1] == [
        b"message-from-tunnel-1"
    ]

    assert destinations[1][1] == [
        b"message-from-tunnel-2"
    ]

    assert destinations[2][1] == [
        b"message-from-tunnel-3"
    ]

    assert all(
        relay.forwarded_messages == 1
        for relay, _ in relays
    )

    for relay, _ in relays:
        await relay.stop()

    for destination, _ in destinations:
        destination.close()
        await destination.wait_closed()


@pytest.mark.asyncio
async def test_tunnels_have_independent_paths():
    tunnel1 = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel1.add_relay(2)
    tunnel1.add_relay(3)
    tunnel1.add_relay(4)

    tunnel2 = Tunnel(
        source_node_id=20,
        destination_node_id=30,
    )

    tunnel2.add_relay(21)
    tunnel2.add_relay(22)
    tunnel2.add_relay(23)

    tunnel3 = Tunnel(
        source_node_id=40,
        destination_node_id=50,
    )

    tunnel3.add_relay(41)
    tunnel3.add_relay(42)
    tunnel3.add_relay(43)

    tunnel1.activate()
    tunnel2.activate()
    tunnel3.activate()

    assert tunnel1.path == [1, 2, 3, 4, 10]
    assert tunnel2.path == [20, 21, 22, 23, 30]
    assert tunnel3.path == [40, 41, 42, 43, 50]

    assert tunnel1.path != tunnel2.path
    assert tunnel2.path != tunnel3.path
    assert tunnel1.path != tunnel3.path


@pytest.mark.asyncio
async def test_tunnels_are_isolated():
    tunnel1 = Tunnel(
        source_node_id=1,
        destination_node_id=10,
    )

    tunnel1.add_relay(2)
    tunnel1.add_relay(3)
    tunnel1.add_relay(4)

    tunnel2 = Tunnel(
        source_node_id=20,
        destination_node_id=30,
    )

    tunnel2.add_relay(21)
    tunnel2.add_relay(22)
    tunnel2.add_relay(23)

    tunnel1.activate()
    tunnel2.activate()

    assert tunnel1.tunnel_id != tunnel2.tunnel_id

    assert tunnel1.source_node_id != tunnel2.source_node_id
    assert tunnel1.destination_node_id != tunnel2.destination_node_id

    assert set(tunnel1.path).isdisjoint(
        set(tunnel2.path)
    )