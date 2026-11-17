import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from file_transfer import (
    FileChunk,
    FileTransfer,
    FileTransferReceiver,
)


def test_file_is_split_into_chunks():
    data = b"A" * 100

    transfer = FileTransfer(
        filename="test.bin",
        data=data,
        chunk_size=30,
    )

    chunks = transfer.chunks()

    assert len(chunks) == 4

    assert chunks[0].payload == (
        b"A" * 30
    )

    assert chunks[1].payload == (
        b"A" * 30
    )

    assert chunks[2].payload == (
        b"A" * 30
    )

    assert chunks[3].payload == (
        b"A" * 10
    )


def test_empty_file_creates_one_chunk():
    transfer = FileTransfer(
        filename="empty.txt",
        data=b"",
        chunk_size=32,
    )

    chunks = transfer.chunks()

    assert len(chunks) == 1
    assert chunks[0].payload == b""


def test_chunk_can_be_converted_to_application_message():
    chunk = FileChunk(
        transfer_id=transfer_id(),
        filename="test.txt",
        file_size=11,
        chunk_index=0,
        total_chunks=1,
        file_hash=sha256(b"hello world"),
        payload=b"hello world",
    )

    message = (
        chunk.to_application_message()
    )

    assert (
        message.message_type
        == "FILE_CHUNK"
    )

    restored = (
        FileChunk.from_application_message(
            message
        )
    )

    assert (
        restored.transfer_id
        == chunk.transfer_id
    )

    assert (
        restored.filename
        == chunk.filename
    )

    assert (
        restored.file_size
        == chunk.file_size
    )

    assert (
        restored.chunk_index
        == chunk.chunk_index
    )

    assert (
        restored.total_chunks
        == chunk.total_chunks
    )

    assert (
        restored.file_hash
        == chunk.file_hash
    )

    assert (
        restored.payload
        == chunk.payload
    )


def test_receiver_reassembles_file():
    data = (
        b"Hello overlay network! "
        * 100
    )

    transfer = FileTransfer(
        filename="message.txt",
        data=data,
        chunk_size=50,
    )

    chunks = transfer.chunks()

    receiver = FileTransferReceiver()

    result = None

    for chunk in chunks:
        result = receiver.receive_chunk(
            chunk
        )

    assert result == data


def test_receiver_accepts_chunks_in_any_order():
    data = (
        b"0123456789"
        * 100
    )

    transfer = FileTransfer(
        filename="unordered.bin",
        data=data,
        chunk_size=25,
    )

    chunks = transfer.chunks()

    receiver = FileTransferReceiver()

    result = None

    for chunk in reversed(chunks):
        result = receiver.receive_chunk(
            chunk
        )

    assert result == data


def test_tampered_file_is_rejected():
    data = (
        b"secure file data"
        * 20
    )

    transfer = FileTransfer(
        filename="secure.bin",
        data=data,
        chunk_size=32,
    )

    chunks = transfer.chunks()

    # Изменяем данные одного чанка.
    tampered = chunks[1]

    chunks[1] = FileChunk(
        transfer_id=tampered.transfer_id,
        filename=tampered.filename,
        file_size=tampered.file_size,
        chunk_index=tampered.chunk_index,
        total_chunks=tampered.total_chunks,
        file_hash=tampered.file_hash,
        payload=b"X" * len(tampered.payload),
    )

    receiver = FileTransferReceiver()

    with pytest.raises(
        ValueError,
        match="File integrity check failed",
    ):
        for chunk in chunks:
            receiver.receive_chunk(
                chunk
            )


def test_different_transfers_have_different_ids():
    first = FileTransfer(
        filename="a.txt",
        data=b"hello",
    )

    second = FileTransfer(
        filename="b.txt",
        data=b"hello",
    )

    assert (
        first.transfer_id
        != second.transfer_id
    )


def test_large_file_is_reassembled():
    data = bytes(
        range(256)
    ) * 1000

    transfer = FileTransfer(
        filename="large.bin",
        data=data,
        chunk_size=1024,
    )

    receiver = FileTransferReceiver()

    for chunk in transfer.chunks():
        result = receiver.receive_chunk(
            chunk
        )

    assert result == data


def transfer_id():
    from uuid import uuid4

    return uuid4()


def sha256(data):
    import hashlib

    return hashlib.sha256(
        data
    ).hexdigest()