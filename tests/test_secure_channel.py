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


def test_encrypt_decrypt():
    key = b"A" * 32

    channel = SecureChannel(key)

    plaintext = b"secret overlay message"

    encrypted = channel.encrypt(
        plaintext
    )

    decrypted = channel.decrypt(
        encrypted
    )

    assert decrypted == plaintext


def test_tampered_ciphertext_is_rejected():
    key = b"A" * 32

    channel = SecureChannel(key)

    plaintext = b"secret overlay message"

    encrypted = bytearray(
        channel.encrypt(plaintext)
    )

    # Меняем один байт ciphertext.
    encrypted[-1] ^= 0x01

    with pytest.raises(Exception):
        channel.decrypt(
            bytes(encrypted)
        )


def test_wrong_key_is_rejected():
    key_a = b"A" * 32
    key_b = b"B" * 32

    sender = SecureChannel(key_a)
    receiver = SecureChannel(key_b)

    plaintext = b"secret overlay message"

    encrypted = sender.encrypt(
        plaintext
    )

    with pytest.raises(Exception):
        receiver.decrypt(
            encrypted
        )


def test_wrong_aad_is_rejected():
    key = b"A" * 32

    sender = SecureChannel(key)
    receiver = SecureChannel(key)

    plaintext = b"secret overlay message"

    encrypted = sender.encrypt(
        plaintext,
        associated_data=b"tunnel-1",
    )

    with pytest.raises(Exception):
        receiver.decrypt(
            encrypted,
            associated_data=b"tunnel-2",
        )