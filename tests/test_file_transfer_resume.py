import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from file_transfer import (
    FileTransfer,
    FileTransferResume,
)


def make_transfer():
    return FileTransfer(
        filename="resume.bin",
        data=b"ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        chunk_size=5,
    )


def test_resume_tracks_acknowledged_chunks():
    transfer = make_transfer()

    resume = FileTransferResume(
        transfer
    )

    assert resume.total_chunks == 6
    assert resume.acknowledged_count == 0
    assert not resume.is_complete

    resume.acknowledge(0)
    resume.acknowledge(1)

    assert resume.acknowledged_chunks == {
        0,
        1,
    }

    assert resume.acknowledged_count == 2


def test_resume_returns_only_pending_chunks():
    transfer = make_transfer()

    resume = FileTransferResume(
        transfer
    )

    resume.acknowledge(0)
    resume.acknowledge(1)
    resume.acknowledge(3)

    assert (
        resume.pending_chunk_indices()
        == [2, 4, 5]
    )

    chunks = resume.pending_chunks()

    assert [
        chunk.chunk_index
        for chunk in chunks
    ] == [2, 4, 5]


def test_resume_returns_next_pending_chunk():
    transfer = make_transfer()

    resume = FileTransferResume(
        transfer
    )

    assert (
        resume.next_pending_chunk()
        .chunk_index
        == 0
    )

    resume.acknowledge(0)
    resume.acknowledge(1)

    assert (
        resume.next_pending_chunk()
        .chunk_index
        == 2
    )


def test_resume_detects_completed_transfer():
    transfer = make_transfer()

    resume = FileTransferResume(
        transfer
    )

    for index in range(
        transfer.total_chunks
    ):
        resume.acknowledge(index)

    assert resume.is_complete
    assert resume.pending_chunks() == []
    assert resume.next_pending_chunk() is None


def test_resume_rejects_unknown_chunk():
    transfer = make_transfer()

    resume = FileTransferResume(
        transfer
    )

    with pytest.raises(
        ValueError,
        match="Unknown chunk index",
    ):
        resume.acknowledge(999)


def test_resume_remembers_last_acknowledged_chunk():
    transfer = make_transfer()

    resume = FileTransferResume(
        transfer
    )

    assert (
        resume.last_acknowledged_chunk()
        is None
    )

    resume.acknowledge(0)
    resume.acknowledge(2)

    assert (
        resume.last_acknowledged_chunk()
        == 2
    )

    resume.acknowledge(1)

    assert (
        resume.last_acknowledged_chunk()
        == 2
    )