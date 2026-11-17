import time

from dht_messages import NodeRecord
from dht_storage import DHTStorage
from identity import Identity


class DHTRepublisher:
    def __init__(
        self,
        identity: Identity,
        storage: DHTStorage,
    ):
        self.identity = identity
        self.storage = storage

    def republish(
        self,
        node_id: str,
        now: int | None = None,
    ) -> NodeRecord:
        """
        Refreshes a NodeRecord before its TTL expires.

        The NodeID, addresses, alias and sequence number remain
        unchanged. issued_at and expires_at are refreshed,
        and the record is signed again.
        """

        if now is None:
            now = int(time.time())

        record = self.storage.records.get(node_id)

        if record is None:
            raise ValueError("NodeRecord not found")

        if record.node_id != self.identity.node_id:
            raise ValueError("Cannot republish another node's record")

        ttl = record.expires_at - record.issued_at

        if ttl <= 0:
            raise ValueError("Invalid NodeRecord TTL")

        refreshed_record = NodeRecord.create_signed(
            identity=self.identity,
            addresses=list(record.addresses),
            sequence_number=record.sequence_number,
            issued_at=now,
            expires_at=now + ttl,
            alias=record.alias,
        )

        self.storage.store(refreshed_record)

        return refreshed_record

    def should_republish(
        self,
        node_id: str,
        now: int | None = None,
    ) -> bool:
        """
        Returns True when the record has reached
        the republish threshold: TTL/2 remaining.
        """

        if now is None:
            now = int(time.time())

        record = self.storage.records.get(node_id)

        if record is None:
            return False

        ttl = record.expires_at - record.issued_at

        if ttl <= 0:
            return True

        remaining = record.expires_at - now

        return remaining <= ttl / 2

    def republish_due_records(
        self,
        now: int | None = None,
    ) -> list[NodeRecord]:
        """
        Republishes every local record that reached
        the TTL/2 threshold.

        Returns the refreshed records.
        """

        if now is None:
            now = int(time.time())

        refreshed = []

        node_ids = list(self.storage.records.keys())

        for node_id in node_ids:
            if not self.should_republish(
                node_id=node_id,
                now=now,
            ):
                continue

            refreshed_record = self.republish(
                node_id=node_id,
                now=now,
            )

            refreshed.append(refreshed_record)

        return refreshed