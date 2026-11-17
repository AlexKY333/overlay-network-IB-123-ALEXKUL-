import json
from dataclasses import dataclass, asdict
from uuid import UUID


@dataclass
class TunnelHop:
    node_id: str
    host: str
    port: int


@dataclass
class TunnelBuildRequest:
    tunnel_id: str
    next_host: str
    next_port: int
    remaining_hops: list[dict]  # список словарей TunnelHop для следующих узлов

    def encode(self) -> bytes:
        data = {
            "tunnel_id": self.tunnel_id,
            "next_host": self.next_host,
            "next_port": self.next_port,
            "remaining_hops": self.remaining_hops,
        }
        return json.dumps(data).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "TunnelBuildRequest":
        payload = json.loads(data.decode("utf-8"))
        return cls(
            tunnel_id=payload["tunnel_id"],
            next_host=payload["next_host"],
            next_port=payload["next_port"],
            remaining_hops=payload.get("remaining_hops", []),
        )


@dataclass
class TunnelBuildResponse:
    tunnel_id: str
    success: bool
    error: str = ""

    def encode(self) -> bytes:
        data = {
            "tunnel_id": self.tunnel_id,
            "success": self.success,
            "error": self.error,
        }
        return json.dumps(data).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "TunnelBuildResponse":
        payload = json.loads(data.decode("utf-8"))
        return cls(
            tunnel_id=payload["tunnel_id"],
            success=payload["success"],
            error=payload.get("error", ""),
        )


@dataclass
class TunnelDataPayload:
    tunnel_id: str
    data: str  # Hex-encoded зашифрованные данные или полезная нагрузка

    def encode(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "TunnelDataPayload":
        payload = json.loads(data.decode("utf-8"))
        return cls(
            tunnel_id=payload["tunnel_id"],
            data=payload["data"],
        )