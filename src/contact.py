from dataclasses import dataclass
from datetime import datetime


@dataclass
class Contact:
    node_id: str
    host: str
    port: int
    last_seen: datetime | None = None

def node_id_to_int(node_id: str) -> int:
    return int(node_id, 16)


def xor_distance(node_id_a: str, node_id_b: str) -> int:
    value_a = node_id_to_int(node_id_a)
    value_b = node_id_to_int(node_id_b)

    return value_a ^ value_b