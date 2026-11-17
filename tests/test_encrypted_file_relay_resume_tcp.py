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

from encrypted_tunnel import EncryptedTunnel
from file_transfer import (
    FileChunk,
    FileTransfer,
    FileTransferReceiver,
    FileTransferResume,
)
from identity import Identity
from relay_server import RelayServer
from secure_session import SecureSession
from tunnel import Tunnel
from tunnel_recovery import TunnelRecoveryManager


def make_encrypted_tunnels():
    """
    Создаёт две стороны защищённой сессии:

        Node A <---- secure session ----> Node B
    """

    state_dir_a = tempfile.mkdtemp()
    state_dir_b = tempfile.mkdtemp()

    identity_a = Identity(
        state_dir_a
    )

    identity_b = Identity(
        state_dir_b
    )

    session_a = SecureSession(
        identity_a
    )

    session_b = SecureSession(
        identity_b
    )

    hello_a = session_a.create_hello()
    hello_b = session_b.create_hello()

    session_b.accept_hello(
        hello_a
    )

    session_a.accept_hello(
        hello_b
    )

    assert session_a.established
    assert session_b.established

    assert (
        session_a.session_key
        == session_b.session_key
    )

    tunnel_a = Tunnel(
        tunnel_id="resume-recovery-tcp",
        source_node_id=0,
        destination_node_id=4,
        relay_node_ids=[
            1,
            2,
            3,
        ],
    )

    tunnel_b = Tunnel(
        tunnel_id="resume-recovery-tcp",
        source_node_id=0,
        destination_node_id=4,
        relay_node_ids=[
            1,
            2,
            3,
        ],
    )

    tunnel_a.activate()
    tunnel_b.activate()

    encrypted_a = EncryptedTunnel(
        tunnel_a,
        session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel_b,
        session_b,
    )

    return (
        encrypted_a,
        encrypted_b,
    )


async def send_encrypted_chunk(
    host,
    port,
    encrypted_data,
):
    """
    Отправляет один зашифрованный chunk
    по отдельному TCP-соединению.

    Важный момент:

    Если relay не смог доставить сообщение
    и вернул пустой ответ, это считается
    ошибкой маршрута.

    Это необходимо для работы
    TunnelRecoveryManager.
    """

    reader, writer = (
        await asyncio.open_connection(
            host,
            port,
        )
    )

    try:
        writer.write(
            encrypted_data
        )

        await writer.drain()

        response = await asyncio.wait_for(
            reader.read(1024),
            timeout=3,
        )

        # Пустой ответ означает,
        # что сообщение не было доставлено.
        if not response:
            raise ConnectionError(
                "Relay route failed: empty response"
            )

        return response

    finally:
        writer.close()

        await writer.wait_closed()


@pytest.mark.asyncio
async def test_encrypted_file_transfer_automatic_resume_after_relay_failure():

    (
        encrypted_sender,
        encrypted_receiver,
    ) = make_encrypted_tunnels()

    # =================================================
    # ФАЙЛ
    # =================================================

    file_data = (
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        b"0123456789"
        b"resume-after-failure"
    )

    transfer = FileTransfer(
        filename="resume.bin",
        data=file_data,
        chunk_size=10,
    )

    resume = FileTransferResume(
        transfer
    )

    receiver = FileTransferReceiver()

    received_indices = []

    received_chunks = {}

    # =================================================
    # NODE B
    # =================================================

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
                encrypted_receiver
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

            receiver.receive_chunk(
                chunk
            )

            received_indices.append(
                chunk.chunk_index
            )

            received_chunks[
                chunk.chunk_index
            ] = chunk.payload

            writer.write(
                f"ACK:{chunk.chunk_index}".encode()
            )

            await writer.drain()

        finally:
            writer.close()

            await writer.wait_closed()

    destination = await asyncio.start_server(
        destination_handler,
        "127.0.0.1",
        0,
    )

    destination_port = (
        destination.sockets[0]
        .getsockname()[1]
    )

    # =================================================
    # RELAY 3
    #
    # R3 -> Node B
    # =================================================

    relay3 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=destination_port,
    )

    await relay3.start()

    relay3_port = (
        relay3.server
        .sockets[0]
        .getsockname()[1]
    )

    # =================================================
    # RELAY 2
    #
    # Основной маршрут:
    #
    # R2 -> R3
    # =================================================

    relay2 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=relay3_port,
    )

    await relay2.start()

    relay2_port = (
        relay2.server
        .sockets[0]
        .getsockname()[1]
    )

    # =================================================
    # RELAY 4
    #
    # Резервный маршрут:
    #
    # R4 -> R3
    # =================================================

    relay4 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=relay3_port,
    )

    await relay4.start()

    relay4_port = (
        relay4.server
        .sockets[0]
        .getsockname()[1]
    )

    # =================================================
    # RELAY 1
    #
    # Изначально:
    #
    # R1 -> R2
    # =================================================

    relay1 = RelayServer(
        host="127.0.0.1",
        port=0,
        next_host="127.0.0.1",
        next_port=relay2_port,
    )

    await relay1.start()

    relay1_port = (
        relay1.server
        .sockets[0]
        .getsockname()[1]
    )

    # =================================================
    # TUNNEL
    # =================================================

    tunnel = Tunnel(
        tunnel_id="resume-recovery-tcp",
        source_node_id=0,
        destination_node_id=4,
        relay_node_ids=[
            1,
            2,
            3,
        ],
    )

    tunnel.activate()

    # =================================================
    # TUNNEL RECOVERY MANAGER
    #
    # Основной маршрут:
    #
    # R1 -> R2
    #
    # Резервный:
    #
    # R1 -> R4
    # =================================================

    recovery = TunnelRecoveryManager(
        tunnel=tunnel,
        entry_relay=relay1,
        backup_host="127.0.0.1",
        backup_port=relay4_port,
    )

    try:

        chunks = transfer.chunks()

        # =================================================
        # ЭТАП 1
        #
        # Первые два chunk:
        #
        # A -> R1 -> R2 -> R3 -> B
        # =================================================

        for chunk in chunks[:2]:

            encrypted_data = (
                encrypted_sender
                .encrypt_application_message(
                    chunk.to_application_message()
                )
            )

            response = await send_encrypted_chunk(
                "127.0.0.1",
                relay1_port,
                encrypted_data,
            )

            assert (
                response
                == f"ACK:{chunk.chunk_index}".encode()
            )

            resume.acknowledge(
                chunk.chunk_index
            )

        # =================================================
        # Проверяем состояние resume.
        # =================================================

        assert (
            resume.acknowledged_chunks
            == {0, 1}
        )

        assert (
            resume.acknowledged_count
            == 2
        )

        assert (
            resume.last_acknowledged_chunk()
            == 1
        )

        assert (
            resume.pending_chunk_indices()
            == list(
                range(
                    2,
                    transfer.total_chunks,
                )
            )
        )

        # =================================================
        # ЭТАП 2
        #
        # Отключаем R2.
        # =================================================

        await relay2.stop()

        # R1 пока ещё считает,
        # что его следующий hop — R2.

        assert (
            relay1.next_port
            == relay2_port
        )

        assert not recovery.is_recovered

        # =================================================
        # ЭТАП 3
        #
        # Отправляем chunk 2.
        #
        # Первая попытка:
        #
        # A -> R1 -> R2 ❌
        #
        # R2 выключен.
        #
        # send_encrypted_chunk()
        # получает b"" и превращает его
        # в ConnectionError.
        #
        # TunnelRecoveryManager:
        #
        # 1. ловит исключение;
        # 2. переключает R1 -> R4;
        # 3. повторяет отправку.
        # =================================================

        chunk = chunks[2]

        encrypted_data = (
            encrypted_sender
            .encrypt_application_message(
                chunk.to_application_message()
            )
        )

        response = (
            await recovery.send_with_recovery(
                send_encrypted_chunk,
                "127.0.0.1",
                relay1_port,
                encrypted_data,
            )
        )

        # После восстановления
        # должен прийти ACK.

        assert (
            response
            == f"ACK:{chunk.chunk_index}".encode()
        )

        # Теперь chunk 2 подтверждён.

        resume.acknowledge(
            chunk.chunk_index
        )

        # =================================================
        # Проверяем recovery.
        # =================================================

        assert recovery.is_recovered

        assert (
            relay1.next_host
            == "127.0.0.1"
        )

        assert (
            relay1.next_port
            == relay4_port
        )

        # =================================================
        # ЭТАП 4
        #
        # После восстановления отправляем
        # только pending chunks.
        #
        # То есть:
        #
        # 3, 4, 5
        #
        # Chunk 0, 1, 2 повторно НЕ отправляются.
        # =================================================

        pending_before = (
            resume.pending_chunk_indices()
        )

        assert (
            pending_before
            == list(
                range(
                    3,
                    transfer.total_chunks,
                )
            )
        )

        for chunk in resume.pending_chunks():

            encrypted_data = (
                encrypted_sender
                .encrypt_application_message(
                    chunk.to_application_message()
                )
            )

            response = (
                await recovery.send_with_recovery(
                    send_encrypted_chunk,
                    "127.0.0.1",
                    relay1_port,
                    encrypted_data,
                )
            )

            assert (
                response
                == f"ACK:{chunk.chunk_index}".encode()
            )

            resume.acknowledge(
                chunk.chunk_index
            )

        # =================================================
        # ЭТАП 5
        #
        # Передача полностью завершена.
        # =================================================

        assert resume.is_complete

        assert (
            resume.acknowledged_count
            == transfer.total_chunks
        )

        assert (
            resume.pending_chunk_indices()
            == []
        )

        assert (
            resume.last_acknowledged_chunk()
            == transfer.total_chunks - 1
        )

        # =================================================
        # ЭТАП 6
        #
        # Проверяем, что Node B получил
        # все chunks.
        # =================================================

        assert sorted(
            received_indices
        ) == list(
            range(
                transfer.total_chunks
            )
        )

        assert (
            len(received_indices)
            == transfer.total_chunks
        )

        # Каждый chunk должен прийти
        # ровно один раз.
        assert (
            len(set(received_indices))
            == transfer.total_chunks
        )

        # =================================================
        # ЭТАП 7
        #
        # Собираем файл.
        # =================================================

        reconstructed = b"".join(
            received_chunks[index]
            for index in range(
                transfer.total_chunks
            )
        )

        assert (
            reconstructed
            == transfer.data
        )

        # =================================================
        # ЭТАП 8
        #
        # Проверяем SHA-256.
        # =================================================

        reconstructed_hash = (
            hashlib.sha256(
                reconstructed
            ).hexdigest()
        )

        assert (
            reconstructed_hash
            == transfer.file_hash
        )

        # =================================================
        # ЭТАП 9
        #
        # Проверяем статистику.
        # =================================================

        # R1 получил:
        #
        # chunk 0
        # chunk 1
        #
        # chunk 2 — первая попытка
        # chunk 2 — повторная попытка
        #
        # chunk 3
        # chunk 4
        # chunk 5
        #
        # Всего:
        #
        # total_chunks + 1
        #
        assert (
            relay1.forwarded_messages
            == transfer.total_chunks + 1
        )

        # R2 получил только первые два
        # chunks до отказа.

        assert (
            relay2.forwarded_messages
            == 2
        )

        # R4 получил:
        #
        # chunk 2 после recovery
        # chunk 3
        # chunk 4
        # chunk 5
        #
        # Всего 4.

        assert (
            relay4.forwarded_messages
            == 4
        )

        # R3 получил все chunks.

        assert (
            relay3.forwarded_messages
            == transfer.total_chunks
        )

    finally:

        await relay1.stop()
        await relay2.stop()
        await relay3.stop()
        await relay4.stop()

        destination.close()

        await destination.wait_closed()