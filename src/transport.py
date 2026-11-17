import asyncio

from message_types import MessageType
from protocol import Frame
from protocol import HEADER_SIZE
from config import MAX_FRAME_PAYLOAD

class Connection:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def send_frame(self, frame: Frame):
        data = frame.encode()

        self.writer.write(data)
        await self.writer.drain()

    async def receive_frame(self, timeout: float | None = None) -> Frame:
        async def read_frame():
            header = await self.reader.readexactly(HEADER_SIZE)

            # payload_length находится в последних 4 байтах
            # нашего 24-байтового заголовка.
            payload_length = int.from_bytes(
                header[20:24],
                byteorder="big",
            )

            if payload_length > MAX_FRAME_PAYLOAD:
                raise ValueError("Payload is too large")

            payload = await self.reader.readexactly(
                payload_length
            )

            return Frame.decode(
                header + payload
            )

        if timeout is None:
            return await read_frame()

        return await asyncio.wait_for(
            read_frame(),
            timeout=timeout,
        )

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


async def start_server(host: str, port: int, dispatcher):
    async def handle_client(reader, writer):
        connection = Connection(reader, writer)

        try:
            while True:
                frame = await connection.receive_frame(
                    timeout=30.0,
                )

                response = await dispatcher.dispatch(frame)

                await connection.send_frame(response)

        except asyncio.IncompleteReadError:
            print("Соединение закрыто до получения полного кадра")

        except asyncio.TimeoutError:
            print("Соединение закрыто по тайм-ауту")

        finally:
            await connection.close()

    server = await asyncio.start_server(
        handle_client,
        host,
        port,
    )

    print(f"TCP сервер запущен на {host}:{port}")

    async with server:
        await server.serve_forever()