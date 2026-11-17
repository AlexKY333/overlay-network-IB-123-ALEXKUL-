import sys

from pathlib import Path
import tempfile

import pytest


sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)


from encrypted_tunnel import EncryptedTunnel
from identity import Identity
from secure_session import SecureSession
from tunnel import Tunnel


def create_established_sessions():
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

    return (
        identity_a,
        identity_b,
        session_a,
        session_b,
    )


def test_encrypted_tunnel_transfers_message():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
    ) = create_established_sessions()

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.activate()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    message = (
        b"Hello through encrypted tunnel"
    )

    ciphertext = encrypted_a.encrypt(
        message
    )

    plaintext = encrypted_b.decrypt(
        ciphertext
    )

    assert plaintext == message


def test_encrypted_tunnel_hides_plaintext():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
    ) = create_established_sessions()

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.activate()

    encrypted = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    message = (
        b"SECRET OVERLAY DATA"
    )

    ciphertext = encrypted.encrypt(
        message
    )

    assert message not in ciphertext


def test_encrypted_tunnel_string_message():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
    ) = create_established_sessions()

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.activate()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    message = (
        "Защищённое сообщение"
    )

    ciphertext = encrypted_a.encrypt_message(
        message
    )

    result = encrypted_b.decrypt_message(
        ciphertext
    )

    assert result == message


def test_inactive_tunnel_rejects_encryption():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
    ) = create_established_sessions()

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    encrypted = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    with pytest.raises(RuntimeError):
        encrypted.encrypt(
            b"data"
        )


def test_tampered_tunnel_data_is_rejected():
    (
        identity_a,
        identity_b,
        session_a,
        session_b,
    ) = create_established_sessions()

    tunnel = Tunnel(
        source_node_id=identity_a.node_id,
        destination_node_id=identity_b.node_id,
    )

    tunnel.activate()

    encrypted_a = EncryptedTunnel(
        tunnel=tunnel,
        session=session_a,
    )

    encrypted_b = EncryptedTunnel(
        tunnel=tunnel,
        session=session_b,
    )

    ciphertext = bytearray(
        encrypted_a.encrypt(
            b"protected data"
        )
    )

    ciphertext[-1] ^= 0x01

    with pytest.raises(Exception):
        encrypted_b.decrypt(
            bytes(ciphertext)
        )