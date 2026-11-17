import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Union
from uuid import UUID, uuid4

NodeIdType = Union[str, int]


class TunnelState(str, Enum):
    BUILDING = "BUILDING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    CLOSING = "CLOSING"
    DEAD = "DEAD"

    # Псевдонимы для совместимости
    CREATING = "BUILDING"
    CLOSED = "DEAD"


@dataclass
class Tunnel:
    source_node_id: NodeIdType
    destination_node_id: NodeIdType
    relay_node_ids: list[NodeIdType] = field(default_factory=list)

    tunnel_id: Union[UUID, str] = field(default_factory=uuid4)
    state: TunnelState = TunnelState.BUILDING

    created_at: float = field(default_factory=time.time)
    ttl: float = 300.0
    max_hops: int = 5

    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.source_node_id == self.destination_node_id:
            raise ValueError("Source and destination cannot be the same node")

    def activate(self) -> None:
        if self.state in (TunnelState.CLOSING, TunnelState.DEAD):
            raise RuntimeError("Cannot activate a closing or dead tunnel")
        self.state = TunnelState.ACTIVE

    def degrade(self) -> None:
        if self.state in (TunnelState.CLOSING, TunnelState.DEAD):
            raise RuntimeError("Cannot degrade a closing or dead tunnel")
        self.state = TunnelState.DEGRADED

    def close(self) -> None:
        self.state = TunnelState.DEAD

    def is_expired(self, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        return current > (self.created_at + self.ttl)

    def is_active(self) -> bool:
        return self.state == TunnelState.ACTIVE and not self.is_expired()

    def add_relay(self, node_id: NodeIdType) -> None:
        if self.state in (TunnelState.CLOSING, TunnelState.DEAD):
            raise RuntimeError("Cannot add relay to a closed or dead tunnel")

        if len(self.relay_node_ids) >= self.max_hops:
            raise ValueError(f"Exceeded max_hops limit ({self.max_hops})")

        if node_id in self.relay_node_ids:
            raise ValueError("Relay already exists in tunnel")

        if node_id in (self.source_node_id, self.destination_node_id):
            raise ValueError("Source or destination cannot be a relay")

        self.relay_node_ids.append(node_id)

    @property
    def relay_count(self) -> int:
        return len(self.relay_node_ids)

    @property
    def path(self) -> list[NodeIdType]:
        return [
            self.source_node_id,
            *self.relay_node_ids,
            self.destination_node_id,
        ]

    @property
    def hop_history(self) -> list[NodeIdType]:
        return list(self.path)