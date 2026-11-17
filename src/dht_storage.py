import hashlib
import time

from dht_messages import NodeRecord


class DHTStorage:
    def __init__(self):
        self.records: dict[str, NodeRecord] = {}

    def store(self, record: NodeRecord) -> None:
        now = int(time.time())

        if record.expires_at <= now:
            raise ValueError("NodeRecord has expired")

        existing = self.records.get(record.node_id)

        if existing is not None:
            if record.sequence_number < existing.sequence_number:
                raise ValueError("Sequence number rollback")

        self.records[record.node_id] = record

    def _is_expired(self, record: NodeRecord, now: int | None = None) -> bool:
        current = int(time.time()) if now is None else now
        return record.expires_at <= current

    def get(self, key: str, now: int | None = None) -> NodeRecord | None:
        current = int(time.time()) if now is None else now

        # 1. Прямой поиск по node_id
        record = self.records.get(key)
        if record is not None:
            if self._is_expired(record, current):
                self.records.pop(key, None)
                return None
            return record

        # 2. Поиск по SHA-256("alias:" || normalize(alias)) или SHA-256("node:" || NodeID)
        expired_ids = []
        matched_record = None

        for nid, rec in list(self.records.items()):
            if self._is_expired(rec, current):
                expired_ids.append(nid)
                continue

            if rec.alias:
                try:
                    if NodeRecord.alias_key(rec.alias) == key:
                        matched_record = rec
                        break
                except ValueError:
                    pass

            node_key = hashlib.sha256(f"node:{rec.node_id}".encode("utf-8")).hexdigest()
            if node_key == key:
                matched_record = rec
                break

        for nid in expired_ids:
            self.records.pop(nid, None)

        return matched_record

    def delete(self, node_id: str) -> None:
        self.records.pop(node_id, None)

    def __len__(self) -> int:
        return len(self.records)