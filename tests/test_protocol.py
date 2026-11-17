from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "src")
)

from protocol import Frame


def test_protocol():
    frame = Frame(
        message_type=1,
        payload=b"Hello overlay network!",
    )

    encoded = frame.encode()

    print("Размер кадра:", len(encoded))

    decoded = Frame.decode(encoded)

    print("Тип сообщения:", decoded.message_type)
    print("Payload:", decoded.payload)
    print("Request ID:", decoded.request_id)

    assert decoded.message_type == 1
    assert decoded.payload == b"Hello overlay network!"
    assert decoded.request_id == frame.request_id

    print("TEST PASSED")


if __name__ == "__main__":
    test_protocol()