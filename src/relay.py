from dataclasses import dataclass
from typing import Union
from tunnel import Tunnel

NodeIdType = Union[str, int]


@dataclass
class Relay:
    node_id: NodeIdType
    tunnel: Tunnel
    position: int

    def __post_init__(self):
        if self.node_id not in self.tunnel.relay_node_ids:
            raise ValueError("Relay node is not part of the tunnel")

        if self.position < 0:
            raise ValueError("Relay position must be non-negative")

        if self.position >= self.tunnel.relay_count:
            raise ValueError("Relay position is outside tunnel")

    @property
    def next_hop(self) -> NodeIdType:
        path = self.tunnel.path
        relay_index = self.position + 1
        if relay_index + 1 >= len(path):
            raise RuntimeError("Relay has no next hop")
        return path[relay_index + 1]

    @property
    def previous_hop(self) -> NodeIdType:
        path = self.tunnel.path
        relay_index = self.position + 1
        if relay_index <= 0:
            raise RuntimeError("Relay has no previous hop")
        return path[relay_index - 1]

    def forward(self, message):
        if not self.tunnel.is_active():
            raise RuntimeError("Cannot forward through inactive tunnel")
        return {
            "relay": self.node_id,
            "next_hop": self.next_hop,
            "message": message,
        }