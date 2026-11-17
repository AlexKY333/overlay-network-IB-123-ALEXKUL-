import struct
import uuid
from config import MAX_FRAME_PAYLOAD

PROTOCOL_VERSION = 1

# Формат заголовка:
# version      -> 1 byte
# message_type -> 1 byte
# flags        -> 2 bytes
# request_id   -> 16 bytes
# payload_len  -> 4 bytes
HEADER_FORMAT = "!BBH16sI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


class Frame:
    def __init__(
        self,
        message_type: int,
        payload: bytes = b"",
        flags: int = 0,
        request_id: uuid.UUID | None = None,
    ):
        if len(payload) > MAX_FRAME_PAYLOAD:
            raise ValueError("Payload is too large")

        self.version = PROTOCOL_VERSION
        self.message_type = message_type
        self.flags = flags
        self.request_id = request_id or uuid.uuid4()
        self.payload = payload

    def encode(self) -> bytes:
        header = struct.pack(
            HEADER_FORMAT,
            self.version,
            self.message_type,
            self.flags,
            self.request_id.bytes,
            len(self.payload),
        )

        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "Frame":
        if len(data) < HEADER_SIZE:
            raise ValueError("Incomplete frame header")

        (
            version,
            message_type,
            flags,
            request_id_bytes,
            payload_length,
        ) = struct.unpack(
            HEADER_FORMAT,
            data[:HEADER_SIZE],
        )

        if version != PROTOCOL_VERSION:
            raise ValueError(
                f"Unsupported protocol version: {version}"
            )

        if payload_length > MAX_FRAME_PAYLOAD:
            raise ValueError("Payload is too large")

        expected_size = HEADER_SIZE + payload_length

        if len(data) < expected_size:
            raise ValueError("Incomplete frame payload")

        payload = data[HEADER_SIZE:expected_size]

        return cls(
            message_type=message_type,
            payload=payload,
            flags=flags,
            request_id=uuid.UUID(bytes=request_id_bytes),
        )