from pathlib import Path
import sys
import struct

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from protocol import Frame, HEADER_FORMAT
from message_types import MessageType


def test_invalid_version():
    # Сначала создаём нормальный кадр.
    frame = Frame(
        message_type=MessageType.PING,
        payload=b"Hello!",
    )

    data = bytearray(frame.encode())

    # Первый байт заголовка — версия протокола.
    # Меняем её с 1 на неподдерживаемую 99.
    data[0] = 99

    print("Отправляем кадр с версией протокола:", data[0])

    try:
        Frame.decode(bytes(data))

    except ValueError as error:
        print("Получена ожидаемая ошибка:")
        print(error)

    else:
        raise AssertionError(
            "Кадр с неподдерживаемой версией был принят"
        )

    print("INVALID VERSION TEST PASSED")


test_invalid_version()