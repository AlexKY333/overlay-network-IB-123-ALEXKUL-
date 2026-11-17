import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from application_message import ApplicationMessage


def test_application_message_encode_decode():
    message_id = uuid4()

    message = ApplicationMessage(
        message_type="TEXT",
        payload=b"Hello overlay network!",
        message_id=message_id,
    )

    encoded = message.encode()

    decoded = ApplicationMessage.decode(
        encoded
    )

    assert decoded.message_id == message_id
    assert decoded.message_type == "TEXT"
    assert decoded.payload == (
        b"Hello overlay network!"
    )


def test_application_message_generates_id():
    message = ApplicationMessage(
        message_type="TEXT",
        payload=b"Hello",
    )

    assert message.message_id is not None


def test_application_message_rejects_empty_type():
    with pytest.raises(ValueError):
        ApplicationMessage(
            message_type="",
            payload=b"Hello",
        )


def test_application_message_rejects_non_bytes_payload():
    with pytest.raises(TypeError):
        ApplicationMessage(
            message_type="TEXT",
            payload="Hello",
        )


def test_application_message_rejects_invalid_data():
    with pytest.raises(ValueError):
        ApplicationMessage.decode(
            b"invalid"
        )


def test_application_message_preserves_binary_payload():
    payload = bytes(
        range(256)
    )

    message = ApplicationMessage(
        message_type="BINARY",
        payload=payload,
    )

    decoded = ApplicationMessage.decode(
        message.encode()
    )

    assert decoded.payload == payload