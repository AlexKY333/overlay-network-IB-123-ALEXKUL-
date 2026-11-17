import asyncio
import hashlib
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
from file_transfer import (
    FileChunk,
    FileTransfer,
    FileTransferReceiver,
)
from application_message import ApplicationMessage
from relay_server import RelayServer


async def create_destination_server(
    encrypted_tunnel: EncryptedTunnel,
    receiver: FileTransferReceiver,
    received_files: list,
    errors: list,
):
    async def handle_client(reader, writer):
        try:
            encrypted_data = await reader.read(
                1024 * 1024
            )

            if not encrypted_data:
                return

            # Расшифровываем ровно один FILE_CHUNK.
            message = (
                encrypted_tunnel
                .decrypt_application_message(
                    encrypted_data
                )
            )

            chunk = (
                FileChunk
                .from_application_message(
                    message
                )
            )

            result = receiver.receive_chunk(
                chunk
            )

            if result is not None:
                received_files.append(result)

            # Каждый TCP-запрос получает ACK.
            ack = ApplicationMessage(
                message_type="FILE_CHUNK_ACK",
                payload=str(
                    chunk.chunk_index
                ).encode("utf-8"),
            )

            encrypted_ack = (
                encrypted_tunnel
                .encrypt_application_message(
                    ack
                )
            )

            writer.write(encrypted_ack)
            await writer.drain()

        except Exception as exc:
            errors.append(exc)

        finally:
            writer.close()
            await writer.wait_closed()

    return await asyncio.start_server(
        handle_client,
        "127.0.0.1",
        0,
    )


def create_secure_tunnels():
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

    assert session_a.established
    assert session_b.established

    assert (
        session_a.session_key
        == session_b.session_key
    )

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.add_relay(1001)
    tunnel.add_relay(1002)
    tunnel.add_relay(1003)

    tunnel.activate()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    return (
        encrypted_a,
        encrypted_b,
    )


@pytest.mark.asyncio
async def test_encrypted_file_transfer_over_three_tcp_relays():
    """
    Реальная передача файла:

        Node A
          |
        Relay 1
          |
        Relay 2
          |
        Relay 3
          |
        Node B

    Каждый FILE_CHUNK передаётся
    отдельным TCP-соединением.

    FILE_CHUNK:
        ApplicationMessage
            ↓
        AES-256-GCM
            ↓
        Relay 1
            ↓
        Relay 2
            ↓
        Relay 3
            ↓
        Node B
    """

    encrypted_a, encrypted_b = (
        create_secure_tunnels()
    )

    receiver = FileTransferReceiver()

    received_files = []
    errors = []

    destination_server = (
        await create_destination_server(
            encrypted_b,
            receiver,
            received_files,
            errors,
        )
    )

    destination_port = (
        destination_server.sockets[0]
        .getsockname()[1]
    )

    relay3 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    server3 = await relay3.start()

    relay3_port = (
        server3.sockets[0]
        .getsockname()[1]
    )

    relay2 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=relay3_port,
    )

    server2 = await relay2.start()

    relay2_port = (
        server2.sockets[0]
        .getsockname()[1]
    )

    relay1 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=relay2_port,
    )

    server1 = await relay1.start()

    relay1_port = (
        server1.sockets[0]
        .getsockname()[1]
    )

    try:
        # -------------------------------------------------
        # Исходный файл
        # -------------------------------------------------

        original_data = (
            b"Protected overlay network file\n"
            * 500
        )

        original_hash = hashlib.sha256(
            original_data
        ).hexdigest()

        transfer = FileTransfer(
            filename="coursework.txt",
            data=original_data,
            chunk_size=256,
        )

        assert (
            transfer.file_hash
            == original_hash
        )

        encrypted_chunks = (
            transfer.encrypt_chunks(
                encrypted_a
            )
        )

        assert len(encrypted_chunks) == (
            transfer.total_chunks
        )

        assert len(encrypted_chunks) > 1

        # Открытый текст не должен находиться
        # внутри зашифрованных сообщений.
        for encrypted in encrypted_chunks:
            assert (
                b"Protected overlay network file"
                not in encrypted
            )

        # -------------------------------------------------
        # Передаём каждый chunk отдельно
        # -------------------------------------------------

        for index, encrypted in enumerate(
            encrypted_chunks
        ):
            reader, writer = (
                await asyncio.open_connection(
                    "127.0.0.1",
                    relay1_port,
                )
            )

            writer.write(encrypted)
            await writer.drain()

            # Ждём ACK от Node B.
            confirmation = await reader.read(
                1024 * 1024
            )

            writer.close()
            await writer.wait_closed()

            assert confirmation

            confirmation_message = (
                encrypted_a
                .decrypt_application_message(
                    confirmation
                )
            )

            assert (
                confirmation_message.message_type
                == "FILE_CHUNK_ACK"
            )

            acknowledged_index = int(
                confirmation_message.payload.decode(
                    "utf-8"
                )
            )

            assert (
                acknowledged_index
                == index
            )

        # -------------------------------------------------
        # Проверяем отсутствие ошибок на Node B
        # -------------------------------------------------

        assert errors == []

        # -------------------------------------------------
        # Проверяем полностью собранный файл
        # -------------------------------------------------

        assert len(received_files) == 1

        received_data = received_files[0]

        assert received_data == original_data

        assert (
            hashlib.sha256(
                received_data
            ).hexdigest()
            == original_hash
        )

        # После успешной сборки состояние
        # конкретного transfer должно быть очищено.
        assert receiver._transfers == {}

        # -------------------------------------------------
        # Проверяем все три Relay
        # -------------------------------------------------

        expected_chunks = (
            transfer.total_chunks
        )

        assert (
            relay1.forwarded_messages
            == expected_chunks
        )

        assert (
            relay2.forwarded_messages
            == expected_chunks
        )

        assert (
            relay3.forwarded_messages
            == expected_chunks
        )

    finally:
        await relay1.stop()
        await relay2.stop()
        await relay3.stop()

        destination_server.close()
        await destination_server.wait_closed()