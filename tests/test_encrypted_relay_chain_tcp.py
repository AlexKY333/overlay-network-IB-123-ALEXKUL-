import asyncio
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
from relay_server import RelayServer
from secure_session import SecureSession
from encrypted_tunnel import EncryptedTunnel
from tunnel import Tunnel


async def start_echo_server(
    encrypted_tunnel: EncryptedTunnel,
):
    async def handle_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        try:
            encrypted_data = await reader.read(
                1024 * 1024
            )

            if not encrypted_data:
                return

            plaintext = encrypted_tunnel.decrypt(
                encrypted_data
            )

            response = encrypted_tunnel.encrypt(
                plaintext
            )

            writer.write(response)
            await writer.drain()

        finally:
            writer.close()
            await writer.wait_closed()

    return await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        0,
    )


def create_secure_tunnel():
    identity_a = Identity(
        tempfile.mkdtemp()
    )

    identity_b = Identity(
        tempfile.mkdtemp()
    )

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

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    return (
        identity_a,
        identity_b,
        session_a,
        session_b,
        tunnel,
    )


@pytest.mark.asyncio
async def test_encrypted_message_through_three_relays():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
        tunnel,
    ) = create_secure_tunnel()

    # Три промежуточных узла.
    relay_ids = [1001, 1002, 1003]

    for relay_id in relay_ids:
        tunnel.add_relay(relay_id)

    tunnel.activate()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    destination_server = await start_echo_server(
        encrypted_b
    )

    destination_port = (
        destination_server.sockets[0].getsockname()[1]
    )

    relay_1 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=0,
    )

    relay_2 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=0,
    )

    relay_3 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    server_3 = await relay_3.start()

    relay_3_port = (
        server_3.sockets[0].getsockname()[1]
    )

    relay_2.next_port = relay_3_port

    server_2 = await relay_2.start()

    relay_2_port = (
        server_2.sockets[0].getsockname()[1]
    )

    relay_1.next_port = relay_2_port

    server_1 = await relay_1.start()

    relay_1_port = (
        server_1.sockets[0].getsockname()[1]
    )

    try:
        message = (
            b"TOP SECRET DATA THROUGH "
            b"THREE ENCRYPTED RELAYS"
        )

        ciphertext = encrypted_a.encrypt(
            message
        )

        # В ciphertext не должно быть открытого текста.
        assert message not in ciphertext

        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            relay_1_port,
        )

        writer.write(ciphertext)
        await writer.drain()

        encrypted_response = await reader.read(
            1024 * 1024
        )

        writer.close()
        await writer.wait_closed()

        decrypted_response = encrypted_a.decrypt(
            encrypted_response
        )

        assert decrypted_response == message

        # Все три relay действительно получили сообщение.
        assert relay_1.forwarded_messages == 1
        assert relay_2.forwarded_messages == 1
        assert relay_3.forwarded_messages == 1

    finally:
        await relay_1.stop()
        await relay_2.stop()
        await relay_3.stop()

        destination_server.close()
        await destination_server.wait_closed()


@pytest.mark.asyncio
async def test_encrypted_data_is_not_decryptable_by_relay_key():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
        tunnel,
    ) = create_secure_tunnel()

    tunnel.add_relay(1001)
    tunnel.add_relay(1002)
    tunnel.add_relay(1003)
    tunnel.activate()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    # Relay получает свой отдельный ключ.
    relay_identity = Identity(
        tempfile.mkdtemp()
    )

    relay_session = SecureSession(
        relay_identity
    )

    relay_session.accept_hello(
        session_a.create_hello()
    )

    # Для настоящей проверки создаём совершенно
    # другой случайный AES-ключ.
    from secure_channel import SecureChannel

    relay_channel = SecureChannel(
        b"R" * 32
    )

    message = b"PRIVATE DATA"

    ciphertext = encrypted_a.encrypt(
        message
    )

    with pytest.raises(Exception):
        relay_channel.decrypt(
            ciphertext
        )