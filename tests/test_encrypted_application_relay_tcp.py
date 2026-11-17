import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from identity import Identity
from secure_session import SecureSession
from tunnel import Tunnel
from encrypted_tunnel import EncryptedTunnel
from application_message import ApplicationMessage
from relay_server import RelayServer


async def start_destination_server(
    host: str,
    port: int,
    encrypted_tunnel: EncryptedTunnel,
):
    async def handle_client(reader, writer):
        try:
            encrypted_data = await reader.read(
                1024 * 1024
            )

            assert encrypted_data

            # На Node B расшифровываем
            # прикладное сообщение.
            message = (
                encrypted_tunnel.decrypt_application_message(
                    encrypted_data
                )
            )

            assert message.message_type == "TEXT"
            assert message.payload == (
                b"Hello from Node A"
            )

            # Создаём ответ с тем же message_id.
            response = ApplicationMessage(
                message_type="TEXT",
                payload=b"Hello from Node B",
                message_id=message.message_id,
            )

            encrypted_response = (
                encrypted_tunnel.encrypt_application_message(
                    response
                )
            )

            writer.write(encrypted_response)
            await writer.drain()

        finally:
            writer.close()
            await writer.wait_closed()

    return await __import__("asyncio").start_server(
        handle_client,
        host,
        port,
    )


@pytest.mark.asyncio
async def test_encrypted_application_message_over_three_relays():
    """
    Реальная TCP-цепочка:

        Node A
          |
        Relay 1
          |
        Relay 2
          |
        Relay 3
          |
        Node B

    ApplicationMessage:
        Node A создаёт TEXT;
        сообщение шифруется;
        проходит через 3 TCP relay;
        Node B расшифровывает и декодирует;
        Node B отправляет зашифрованный ответ;
        Node A получает и проверяет ответ.
    """

    import asyncio

    # -------------------------------------------------
    # Identity
    # -------------------------------------------------

    identity_a = Identity(
        tempfile.mkdtemp()
    )

    identity_b = Identity(
        tempfile.mkdtemp()
    )

    # -------------------------------------------------
    # Secure session
    # -------------------------------------------------

    session_a = SecureSession(
        identity_a
    )

    session_b = SecureSession(
        identity_b
    )

    hello_a = session_a.create_hello()
    hello_b = session_b.create_hello()

    session_a.accept_hello(
        hello_b
    )

    session_b.accept_hello(
        hello_a
    )

    assert session_a.established
    assert session_b.established

    assert (
        session_a.session_key
        == session_b.session_key
    )

    # -------------------------------------------------
    # Tunnel
    # -------------------------------------------------

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.add_relay(1001)
    tunnel.add_relay(1002)
    tunnel.add_relay(1003)

    tunnel.activate()

    assert tunnel.is_active()
    assert tunnel.relay_count == 3

    # -------------------------------------------------
    # Encrypted tunnels
    # -------------------------------------------------

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    # -------------------------------------------------
    # TCP addresses
    # -------------------------------------------------

    destination_server = await start_destination_server(
        "127.0.0.1",
        0,
        encrypted_b,
    )

    destination_port = (
        destination_server.sockets[0].getsockname()[1]
    )

    relay3 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    relay2 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=0,
    )

    relay1 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=0,
    )

    # Сначала запускаем Relay 3,
    # чтобы получить его реальный порт.
    server3 = await relay3.start()

    relay3_port = (
        server3.sockets[0].getsockname()[1]
    )

    # Relay 2 → Relay 3
    relay2.next_port = relay3_port

    server2 = await relay2.start()

    relay2_port = (
        server2.sockets[0].getsockname()[1]
    )

    # Relay 1 → Relay 2
    relay1.next_port = relay2_port

    server1 = await relay1.start()

    relay1_port = (
        server1.sockets[0].getsockname()[1]
    )

    try:
        # -------------------------------------------------
        # Node A создаёт ApplicationMessage
        # -------------------------------------------------

        original_message = ApplicationMessage(
            message_type="TEXT",
            payload=b"Hello from Node A",
        )

        original_message_id = (
            original_message.message_id
        )

        encrypted_message = (
            encrypted_a.encrypt_application_message(
                original_message
            )
        )

        # Открытый текст не должен находиться
        # внутри передаваемых данных.
        assert (
            b"Hello from Node A"
            not in encrypted_message
        )

        # -------------------------------------------------
        # Node A → Relay 1
        # -------------------------------------------------

        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            relay1_port,
        )

        writer.write(encrypted_message)
        await writer.drain()

        encrypted_response = await reader.read(
            1024 * 1024
        )

        writer.close()
        await writer.wait_closed()

        # -------------------------------------------------
        # Проверяем ответ Node B
        # -------------------------------------------------

        assert encrypted_response

        assert (
            b"Hello from Node B"
            not in encrypted_response
        )

        response = (
            encrypted_a.decrypt_application_message(
                encrypted_response
            )
        )

        assert response.message_type == "TEXT"

        assert response.payload == (
            b"Hello from Node B"
        )

        # ID сообщения сохраняется через весь туннель.
        assert (
            response.message_id
            == original_message_id
        )

        # -------------------------------------------------
        # Проверяем, что все 3 relay действительно
        # переслали сообщение.
        # -------------------------------------------------

        assert relay1.forwarded_messages == 1
        assert relay2.forwarded_messages == 1
        assert relay3.forwarded_messages == 1

    finally:
        await relay1.stop()
        await relay2.stop()
        await relay3.stop()

        destination_server.close()
        await destination_server.wait_closed()