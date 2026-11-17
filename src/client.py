import asyncio

from protocol import Frame
from transport import Connection
from message_types import MessageType


async def main():
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        9000,
    )

    connection = Connection(reader, writer)

    frame = Frame(
        message_type=MessageType.PING,
        payload=b"Hello from Node A!",
    )

    print("Отправляем PING...")
    await connection.send_frame(frame)

    response = await connection.receive_frame()

    print(
        f"Получен ответ: "
        f"type={MessageType(response.message_type).name}, "
        f"payload={response.payload!r}"
    )

    await connection.close()


asyncio.run(main())