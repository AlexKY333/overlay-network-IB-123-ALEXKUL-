import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from relay_server import RelayServer
from tunnel import Tunnel
from tunnel_recovery import TunnelRecoveryManager


@pytest.mark.asyncio
async def test_tunnel_recovery_switches_to_backup_relay():

    destination_received = []

    async def destination_handler(
        reader,
        writer,
    ):
        try:
            data = await reader.read(
                1024
            )

            if data:
                destination_received.append(
                    data
                )

                writer.write(
                    b"ACK"
                )

                await writer.drain()

        finally:
            writer.close()
            await writer.wait_closed()

    # -------------------------------------------------
    # Destination
    #
    # B
    # -------------------------------------------------

    destination = await asyncio.start_server(
        destination_handler,
        "127.0.0.1",
        0,
    )

    destination_port = (
        destination.sockets[0]
        .getsockname()[1]
    )

    # -------------------------------------------------
    # Backup relay
    #
    # R4 -> B
    # -------------------------------------------------

    relay4 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    await relay4.start()

    relay4_port = (
        relay4.server
        .sockets[0]
        .getsockname()[1]
    )

    # -------------------------------------------------
    # Entry relay
    #
    # Сначала:
    #
    # R1 -> R2
    #
    # Но R2 не существует.
    # -------------------------------------------------

    relay1 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=65500,
    )

    await relay1.start()

    relay1_port = (
        relay1.server
        .sockets[0]
        .getsockname()[1]
    )

    # -------------------------------------------------
    # Tunnel
    # -------------------------------------------------

    tunnel = Tunnel(
        tunnel_id="recovery-test",
        source_node_id=0,
        destination_node_id=4,
        relay_node_ids=[
            1,
            2,
            3,
        ],
    )

    tunnel.activate()

    # -------------------------------------------------
    # Recovery manager
    # -------------------------------------------------

    recovery = TunnelRecoveryManager(
        tunnel=tunnel,
        entry_relay=relay1,
        backup_host="127.0.0.1",
        backup_port=relay4_port,
    )

    async def send_data(
        host,
        port,
        data,
    ):
        reader, writer = (
            await asyncio.open_connection(
                host,
                port,
            )
        )

        try:
            writer.write(data)

            await writer.drain()

            return await asyncio.wait_for(
                reader.read(1024),
                timeout=2,
            )

        finally:
            writer.close()
            await writer.wait_closed()

    try:

        # -------------------------------------------------
        # Основная попытка:
        #
        # A -> R1 -> R2
        #
        # R2 недоступен.
        #
        # RecoveryManager должен автоматически
        # переключить R1 на R4 и повторить отправку.
        # -------------------------------------------------

        response = (
            await recovery.send_with_recovery(
                send_data,
                "127.0.0.1",
                relay1_port,
                b"hello",
            )
        )

        # -------------------------------------------------
        # Проверяем успешное восстановление.
        # -------------------------------------------------

        assert response == b"ACK"

        assert recovery.is_recovered

        # -------------------------------------------------
        # Проверяем, что R1 переключился
        # на резервный relay.
        # -------------------------------------------------

        assert (
            relay1.next_host
            == "127.0.0.1"
        )

        assert (
            relay1.next_port
            == relay4_port
        )

        # -------------------------------------------------
        # Проверяем доставку до B.
        # -------------------------------------------------

        assert destination_received == [
            b"hello"
        ]

        # -------------------------------------------------
        # R1 получил две попытки:
        #
        # 1. попытка через неработающий R2;
        # 2. повторная попытка через R4.
        # -------------------------------------------------

        assert (
            relay1.forwarded_messages
            == 2
        )

        # -------------------------------------------------
        # R4 получил только успешную попытку.
        # -------------------------------------------------

        assert (
            relay4.forwarded_messages
            == 1
        )

    finally:

        await relay1.stop()
        await relay4.stop()

        destination.close()

        await destination.wait_closed()