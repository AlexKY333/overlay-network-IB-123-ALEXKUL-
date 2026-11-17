from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from protocol import Frame, MAX_FRAME_PAYLOAD
from message_types import MessageType


def test_oversized_payload():
    print("MAX_FRAME_PAYLOAD:", MAX_FRAME_PAYLOAD)

    oversized_payload = b"A" * (MAX_FRAME_PAYLOAD + 1)

    try:
        Frame(
            message_type=MessageType.PING,
            payload=oversized_payload,
        )

    except ValueError as error:
        print("Получена ожидаемая ошибка:")
        print(error)

    else:
        raise AssertionError(
            "Слишком большой payload не был отклонён"
        )

    print("OVERSIZED PAYLOAD TEST PASSED")


test_oversized_payload()