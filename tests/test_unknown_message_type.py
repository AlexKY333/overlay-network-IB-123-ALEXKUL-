from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from protocol import Frame


UNKNOWN_MESSAGE_TYPE = 255


def test_unknown_message_type():
    frame = Frame(
        message_type=UNKNOWN_MESSAGE_TYPE,
        payload=b"test",
    )

    encoded = frame.encode()

    decoded = Frame.decode(encoded)

    print(
        "Получен тип сообщения:",
        decoded.message_type
    )

    assert decoded.message_type == UNKNOWN_MESSAGE_TYPE

    print("UNKNOWN MESSAGE TYPE TEST PASSED")


if __name__ == "__main__":
    test_unknown_message_type()