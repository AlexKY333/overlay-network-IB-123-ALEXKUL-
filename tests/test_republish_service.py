import sys
import time
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

import pytest

from dht_messages import NodeRecord
from dht_storage import DHTStorage
from identity import Identity
from republisher import DHTRepublisher
from republish_service import DHTRepublishService


def create_record(
    identity: Identity,
    issued_at: int,
    expires_at: int,
) -> NodeRecord:
    return NodeRecord.create_signed(
        identity=identity,
        addresses=[
            "127.0.0.1:9000"
        ],
        sequence_number=1,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def test_service_interval_validation(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    republisher = DHTRepublisher(
        identity=identity,
        storage=storage,
    )

    with pytest.raises(ValueError):
        DHTRepublishService(
            republisher=republisher,
            interval=0,
        )

    with pytest.raises(ValueError):
        DHTRepublishService(
            republisher=republisher,
            interval=-1,
        )


@pytest.mark.asyncio
async def test_run_once_republishes_due_records(
    tmp_path,
    monkeypatch,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    now = int(time.time())

    record = create_record(
        identity=identity,
        issued_at=now,
        expires_at=now + 1,
    )

    storage.store(record)

    republisher = DHTRepublisher(
        identity=identity,
        storage=storage,
    )

    service = DHTRepublishService(
        republisher=republisher,
        interval=0.05,
    )

    # Используем время, при котором запись уже
    # достигла половины TTL.
    refresh_time = now + 1

    monkeypatch.setattr(
        "republisher.time.time",
        lambda: refresh_time,
    )

    refreshed = await service.run_once()

    assert refreshed == 1

    stored = storage.get(
        identity.node_id
    )

    assert stored is not None
    assert stored.issued_at == refresh_time
    assert stored.expires_at == refresh_time + 1
    assert stored.verify_signature()


@pytest.mark.asyncio
async def test_background_service_starts_and_stops(
    tmp_path,
):
    identity = Identity(
        tmp_path / "identity"
    )

    storage = DHTStorage()

    republisher = DHTRepublisher(
        identity=identity,
        storage=storage,
    )

    service = DHTRepublishService(
        republisher=republisher,
        interval=0.01,
    )

    assert service.running is False

    service.start()

    # Даём asyncio возможность запустить task.
    await asyncio_sleep_short()

    assert service.running is True

    await service.stop()

    assert service.running is False


async def asyncio_sleep_short():
    import asyncio

    await asyncio.sleep(0.02)