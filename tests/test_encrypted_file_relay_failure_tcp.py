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
from secure_session import SecureSession
from tunnel import Tunnel
from encrypted_tunnel import EncryptedTunnel
from file_transfer import FileChunk, FileTransfer, FileTransferReceiver
from application_message import ApplicationMessage
from relay_server import RelayServer


def create_secure_tunnels():
    identity_a = Identity(
        tempfile.mkdtemp()
    )

    identity_b = Identity(
        tempfile.mkdtemp()
    )

    session_a = SecureSession(identity_a)
    session_b = SecureSession(identity_b)

    hello_a = session_a.create_hello()
    hello_b = session_b.create_hello()

    session_a.accept_hello(hello_b)
    session_b.accept_hello(hello_a)

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

    return encrypted_a, encrypted_b


@pytest.mark.asyncio
async def test_encrypted_file_transfer_detects_relay_failure():
    """
    Проверяет отказоустойчивость передачи файла.

    До отказа:

        Node A
          |
        Relay 1
          |
        Relay 2
          |
        Relay 3
          |
        Node B

    Первый chunk успешно проходит всю цепочку.

    Затем Relay 2 отключается:

        Node A
          |
        Relay 1
          |
        X Relay 2
          |
        Relay 3
          |
        Node B

    Следующий chunk не должен попасть на Node B.
    """

    encrypted_a, encrypted_b = (
        create_secure_tunnels()
    )

    receiver = FileTransferReceiver()

    received_chunks = []
    destination_errors = []

    async def destination_handler(
        reader,
        writer,
    ):
        try:
            encrypted_data = await reader.read(
                1024 * 1024
            )

            if not encrypted_data:
                return

            message = (
                encrypted_b
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

            received_chunks.append(
                chunk.chunk_index
            )

            ack = ApplicationMessage(
                message_type="FILE_CHUNK_ACK",
                payload=str(
                    chunk.chunk_index
                ).encode("utf-8"),
            )

            encrypted_ack = (
                encrypted_b
                .encrypt_application_message(
                    ack
                )
            )

            writer.write(encrypted_ack)
            await writer.drain()

        except Exception as exc:
            destination_errors.append(exc)

        finally:
            writer.close()
            await writer.wait_closed()

    destination_server = await asyncio.start_server(
        destination_handler,
        "127.0.0.1",
        0,
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
        # Создаём файл из нескольких чанков
        # -------------------------------------------------

        original_data = (
            b"Failure recovery test data\n"
            * 100
        )

        transfer = FileTransfer(
            filename="failure-test.txt",
            data=original_data,
            chunk_size=128,
        )

        chunks = transfer.chunks()

        assert len(chunks) >= 2

        encrypted_chunks = (
            transfer.encrypt_chunks(
                encrypted_a
            )
        )

        # -------------------------------------------------
        # CHUNK 0 — всё работает
        # -------------------------------------------------

        reader, writer = (
            await asyncio.open_connection(
                "127.0.0.1",
                relay1_port,
            )
        )

        writer.write(
            encrypted_chunks[0]
        )

        await writer.drain()

        ack = await reader.read(
            1024 * 1024
        )

        assert ack

        ack_message = (
            encrypted_a
            .decrypt_application_message(
                ack
            )
        )

        assert (
            ack_message.message_type
            == "FILE_CHUNK_ACK"
        )

        assert (
            int(
                ack_message.payload.decode(
                    "utf-8"
                )
            )
            == 0
        )

        writer.close()
        await writer.wait_closed()

        # Первый chunk действительно дошёл.
        assert received_chunks == [0]

        # Все три relay обработали его.
        assert relay1.forwarded_messages == 1
        assert relay2.forwarded_messages == 1
        assert relay3.forwarded_messages == 1

        # -------------------------------------------------
        # ОТКАЗ RELAY 2
        # -------------------------------------------------

        await relay2.stop()

        # -------------------------------------------------
        # CHUNK 1 — Relay 2 уже отключён
        # -------------------------------------------------

        reader, writer = (
            await asyncio.open_connection(
                "127.0.0.1",
                relay1_port,
            )
        )

        writer.write(
            encrypted_chunks[1]
        )

        await writer.drain()

        # Relay 1 не может подключиться к Relay 2,
        # поэтому ответа от Node B быть не должно.
        try:
            failed_response = await asyncio.wait_for(
                reader.read(1024 * 1024),
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            # Relay 2 отключён, поэтому Relay 1
            # не может завершить пересылку.
            # Отсутствие ответа считаем обнаруженным отказом.
            failed_response = b""

        writer.close()
        await writer.wait_closed()

        assert failed_response == b""

        # -------------------------------------------------
        # Проверяем, что второй chunk НЕ дошёл
        # -------------------------------------------------

        assert received_chunks == [0]

        # Relay 1 получил запрос на второй chunk,
        # но Relay 2 его уже не получил.
        assert relay1.forwarded_messages == 2
        assert relay2.forwarded_messages == 1
        assert relay3.forwarded_messages == 1

        # Node B не должен получить никаких ошибок
        # при обработке уже успешно доставленного chunk.
        assert destination_errors == []

        # Передача не завершена:
        # receiver всё ещё ждёт остальные chunks.
        assert transfer.transfer_id in (
            receiver._transfers
        )

    finally:
        await relay1.stop()
        await relay2.stop()
        await relay3.stop()

        destination_server.close()
        await destination_server.wait_closed()