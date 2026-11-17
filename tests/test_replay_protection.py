import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from secure_channel import SecureChannel


def test_replayed_packet_is_rejected():
    key = b"A" * 32

    sender = SecureChannel(key)
    receiver = SecureChannel(key)

    message = b"SECRET MESSAGE"

    encrypted = sender.encrypt(message)

    assert receiver.decrypt(encrypted) == message

    with pytest.raises(
        ValueError,
        match="Replay attack detected",
    ):
        receiver.decrypt(encrypted)


def test_two_different_messages_are_accepted():
    key = b"B" * 32

    sender = SecureChannel(key)
    receiver = SecureChannel(key)

    first = sender.encrypt(
        b"FIRST MESSAGE"
    )

    second = sender.encrypt(
        b"SECOND MESSAGE"
    )

    assert receiver.decrypt(first) == b"FIRST MESSAGE"
    assert receiver.decrypt(second) == b"SECOND MESSAGE"


def test_old_packet_cannot_be_replayed_after_new_packet():
    key = b"C" * 32

    sender = SecureChannel(key)
    receiver = SecureChannel(key)

    first = sender.encrypt(
        b"FIRST"
    )

    second = sender.encrypt(
        b"SECOND"
    )

    assert receiver.decrypt(first) == b"FIRST"
    assert receiver.decrypt(second) == b"SECOND"

    with pytest.raises(
        ValueError,
        match="Replay attack detected",
    ):
        receiver.decrypt(first)


def test_sequence_number_is_authenticated():
    key = b"D" * 32

    sender = SecureChannel(key)
    receiver = SecureChannel(key)

    encrypted = bytearray(
        sender.encrypt(
            b"IMPORTANT DATA"
        )
    )

    # Меняем sequence number.
    encrypted[7] ^= 0x01

    with pytest.raises(Exception):
        receiver.decrypt(
            bytes(encrypted)
        )


def test_replay_with_different_associated_data_is_rejected():
    key = b"E" * 32

    sender = SecureChannel(key)
    receiver = SecureChannel(key)

    encrypted = sender.encrypt(
        b"PRIVATE DATA",
        associated_data=b"header-1",
    )

    assert receiver.decrypt(
        encrypted,
        associated_data=b"header-1",
    ) == b"PRIVATE DATA"

    with pytest.raises(
        ValueError,
        match="Replay attack detected",
    ):
        receiver.decrypt(
            encrypted,
            associated_data=b"header-1",
        )