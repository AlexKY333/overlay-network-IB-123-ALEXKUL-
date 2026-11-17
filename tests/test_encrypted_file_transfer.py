import sys
import tempfile
from pathlib import Path

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
from file_transfer import (
    FileTransfer,
    FileTransferReceiver,
)


def create_secure_tunnels():
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
        EncryptedTunnel(
            tunnel=tunnel,
            session=session_a,
        ),
        EncryptedTunnel(
            tunnel=tunnel,
            session=session_b,
        ),
    )


def test_file_chunks_are_encrypted():
    encrypted_a, _ = (
        create_secure_tunnels()
    )

    data = (
        b"Hello secure file!"
        * 100
    )

    transfer = FileTransfer(
        filename="test.txt",
        data=data,
        chunk_size=64,
    )

    encrypted_chunks = (
        transfer.encrypt_chunks(
            encrypted_a
        )
    )

    assert len(encrypted_chunks) == (
        transfer.total_chunks
    )

    for encrypted in encrypted_chunks:
        assert b"Hello secure file!" not in encrypted


def test_encrypted_file_is_reassembled():
    encrypted_a, encrypted_b = (
        create_secure_tunnels()
    )

    data = (
        b"Overlay network file transfer "
        * 100
    )

    transfer = FileTransfer(
        filename="network.txt",
        data=data,
        chunk_size=100,
    )

    receiver = FileTransferReceiver()

    result = None

    for encrypted in (
        transfer.encrypt_chunks(
            encrypted_a
        )
    ):
        result = (
            receiver
            .receive_encrypted_message(
                encrypted_b,
                encrypted,
            )
        )

    assert result == data


def test_encrypted_file_chunks_can_arrive_out_of_order():
    encrypted_a, encrypted_b = (
        create_secure_tunnels()
    )

    data = (
        b"0123456789"
        * 200
    )

    transfer = FileTransfer(
        filename="unordered.bin",
        data=data,
        chunk_size=50,
    )

    encrypted_chunks = (
        transfer.encrypt_chunks(
            encrypted_a
        )
    )

    receiver = FileTransferReceiver()

    result = None

    for encrypted in reversed(
        encrypted_chunks
    ):
        result = (
            receiver
            .receive_encrypted_message(
                encrypted_b,
                encrypted,
            )
        )

    assert result == data


def test_tampered_encrypted_file_chunk_is_rejected():
    encrypted_a, encrypted_b = (
        create_secure_tunnels()
    )

    transfer = FileTransfer(
        filename="secure.bin",
        data=b"A" * 500,
        chunk_size=50,
    )

    encrypted_chunks = (
        transfer.encrypt_chunks(
            encrypted_a
        )
    )

    tampered = bytearray(
        encrypted_chunks[0]
    )

    tampered[-1] ^= 0xFF

    receiver = FileTransferReceiver()

    try:
        receiver.receive_encrypted_message(
            encrypted_b,
            bytes(tampered),
        )
    except Exception:
        return

    raise AssertionError(
        "Tampered encrypted file chunk was accepted"
    )


def test_different_file_transfers_have_different_ids():
    encrypted_a, _ = (
        create_secure_tunnels()
    )

    first = FileTransfer(
        filename="first.txt",
        data=b"same data",
    )

    second = FileTransfer(
        filename="second.txt",
        data=b"same data",
    )

    first_chunks = first.encrypt_chunks(
        encrypted_a
    )

    second_chunks = second.encrypt_chunks(
        encrypted_a
    )

    assert first.transfer_id != (
        second.transfer_id
    )

    assert first_chunks[0] != (
        second_chunks[0]
    )