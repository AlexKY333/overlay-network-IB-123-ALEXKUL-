import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from identity import Identity
from secure_session import SecureSession
from tunnel import Tunnel
from encrypted_tunnel import EncryptedTunnel


def create_secure_tunnel():
    identity_a = Identity(
        tempfile.mkdtemp()
    )

    identity_b = Identity(
        tempfile.mkdtemp()
    )

    session_a = SecureSession(
        identity_a
    )

    session_b = SecureSession(
        identity_b
    )

    hello_a = session_a.create_hello()
    hello_b = session_b.create_hello()

    session_a.accept_hello(
        hello_b
    )

    session_b.accept_hello(
        hello_a
    )

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.add_relay(1001)
    tunnel.add_relay(1002)
    tunnel.add_relay(1003)

    tunnel.activate()

    return (
        tunnel,
        session_a,
        session_b,
    )


def test_encrypted_application_message():
    (
        tunnel,
        session_a,
        session_b,
    ) = create_secure_tunnel()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    encrypted = (
        encrypted_a.create_text_message(
            "Hello from Node A"
        )
    )

    assert b"Hello from Node A" not in encrypted

    message = (
        encrypted_b.decrypt_text_message(
            encrypted
        )
    )

    assert message.message_type == "TEXT"
    assert message.payload == (
        b"Hello from Node A"
    )


def test_application_message_has_unique_id():
    (
        tunnel,
        session_a,
        session_b,
    ) = create_secure_tunnel()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    first = encrypted_a.create_text_message(
        "First"
    )

    second = encrypted_a.create_text_message(
        "Second"
    )

    first_message = (
        encrypted_b.decrypt_text_message(
            first
        )
    )

    second_message = (
        encrypted_b.decrypt_text_message(
            second
        )
    )

    assert (
        first_message.message_id
        != second_message.message_id
    )


def test_application_message_replay_is_rejected():
    (
        tunnel,
        session_a,
        session_b,
    ) = create_secure_tunnel()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    encrypted = (
        encrypted_a.create_text_message(
            "Replay protected"
        )
    )

    message = (
        encrypted_b.decrypt_text_message(
            encrypted
        )
    )

    assert message.payload == (
        b"Replay protected"
    )

    with pytest.raises(
        ValueError,
        match="Replay attack detected",
    ):
        encrypted_b.decrypt_text_message(
            encrypted
        )


def test_wrong_application_message_type_rejected():
    (
        tunnel,
        session_a,
        session_b,
    ) = create_secure_tunnel()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    message = (
        encrypted_a.channel.encrypt(
            b"not a valid application message"
        )
    )

    with pytest.raises(
        ValueError
    ):
        encrypted_a.decrypt_text_message(
            message
        )