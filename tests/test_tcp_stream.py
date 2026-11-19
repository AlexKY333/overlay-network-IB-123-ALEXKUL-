import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from message_types import MessageType
from protocol import Frame
from transport import Connection


async def test_multiple_frames():
    server_ready = asyncio.Event()

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)
        try:
            frame1 = await connection.receive_frame()
            frame2 = await connection.receive_frame()
            frame3 = await connection.receive_frame()

            assert frame1.message_type == MessageType.PING
            assert frame2.message_type == MessageType.PING
            assert frame3.message_type == MessageType.PING

            assert frame1.payload == b"first"
            assert frame2.payload == b"second"
            assert frame3.payload == b"third"

            server_ready.set()
        finally:
            await connection.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        frame1 = Frame(message_type=MessageType.PING, payload=b"first")
        frame2 = Frame(message_type=MessageType.PING, payload=b"second")
        frame3 = Frame(message_type=MessageType.PING, payload=b"third")

        # Намеренно отправляем три кадра одним write (склеенное чтение)
        writer.write(frame1.encode() + frame2.encode() + frame3.encode())
        await writer.drain()

        await asyncio.wait_for(server_ready.wait(), timeout=5)

        writer.close()
        await writer.wait_closed()


async def test_100_variable_length_frames_split_and_coalesced():
    """
    Критерий приёмки (Раздел 16 ТЗ):
    100 кадров переменной длины, включая разделённые (внутри заголовка и payload)
    и склеенные чтения, приняты без нарушения границ.
    """
    rng = random.Random(42)
    total_frames = 100
    expected_frames: list[Frame] = []
    received_frames: list[Frame] = []
    done_event = asyncio.Event()

    # Генерируем 100 кадров с разной длиной payload (от 0 до 8192 байт)
    edge_lengths = [0, 1, 7, 24, 63, 255, 1024, 4096, 8192]
    for i in range(total_frames):
        length = edge_lengths[i] if i < len(edge_lengths) else rng.randint(0, 4096)
        payload = rng.randbytes(length)
        msg_type = MessageType.APP_MESSAGE if i % 2 == 0 else MessageType.PING
        expected_frames.append(Frame(message_type=msg_type, payload=payload))

    async def handle_client(reader, writer):
        connection = Connection(reader, writer)
        try:
            for _ in range(total_frames):
                frame = await connection.receive_frame(timeout=5.0)
                received_frames.append(frame)
            done_event.set()
        finally:
            await connection.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        idx = 0
        while idx < total_frames:
            mode = idx % 3

            if mode == 0 and idx + 4 <= total_frames:
                # Режим 1: склеиваем сразу 4 кадра в один write()
                coalesced = b"".join(f.encode() for f in expected_frames[idx : idx + 4])
                writer.write(coalesced)
                await writer.drain()
                idx += 4

            elif mode == 1:
                # Режим 2: режем один кадр прямо внутри 24-байтового заголовка и payload
                raw = expected_frames[idx].encode()
                cuts = sorted({5, 13, 24, min(len(raw), 24 + len(expected_frames[idx].payload) // 2)})
                prev = 0
                for cut in cuts:
                    if cut > prev:
                        writer.write(raw[prev:cut])
                        await writer.drain()
                        await asyncio.sleep(0)
                        prev = cut
                if prev < len(raw):
                    writer.write(raw[prev:])
                    await writer.drain()
                idx += 1

            else:
                # Режим 3: смешанный поток — склеиваем 2 кадра и режем случайными кусками
                batch_end = min(total_frames, idx + 2)
                stream_chunk = b"".join(f.encode() for f in expected_frames[idx:batch_end])
                pos = 0
                while pos < len(stream_chunk):
                    step = rng.randint(1, 37)
                    writer.write(stream_chunk[pos : pos + step])
                    await writer.drain()
                    await asyncio.sleep(0)
                    pos += step
                idx = batch_end

        await asyncio.wait_for(done_event.wait(), timeout=10.0)
        writer.close()
        await writer.wait_closed()

    assert len(received_frames) == total_frames
    for i, (exp, got) in enumerate(zip(expected_frames, received_frames)):
        assert got.message_type == exp.message_type, f"Frame {i}: message_type mismatch"
        assert got.request_id == exp.request_id, f"Frame {i}: request_id mismatch"
        assert got.payload == exp.payload, f"Frame {i}: payload corrupted"

    print(
        f"[OK] Принято {len(received_frames)}/{total_frames} кадров переменной длины "
        f"(склеенные + разрезанные чтения) без нарушения границ."
    )


if __name__ == "__main__":
    asyncio.run(test_multiple_frames())
    asyncio.run(test_100_variable_length_frames_split_and_coalesced())