from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass
class ApplicationMessage:
    """
    Прикладное сообщение поверх защищённого туннеля.

    message_id:
        Уникальный идентификатор сообщения.

    message_type:
        Тип прикладного сообщения.

    payload:
        Полезная нагрузка.
    """

    message_type: str
    payload: bytes
    message_id: UUID = None

    def __post_init__(self):
        if self.message_id is None:
            self.message_id = uuid4()

        if not self.message_type:
            raise ValueError(
                "message_type cannot be empty"
            )

        if not isinstance(self.payload, bytes):
            raise TypeError(
                "payload must be bytes"
            )

    def encode(self) -> bytes:
        """
        Формат:

        UUID
        message_type
        payload length
        payload
        """

        message_id_bytes = (
            str(self.message_id).encode("ascii")
        )

        message_type_bytes = (
            self.message_type.encode("utf-8")
        )

        if len(message_type_bytes) > 255:
            raise ValueError(
                "message_type is too long"
            )

        return (
            len(message_id_bytes).to_bytes(
                1,
                "big",
            )
            + message_id_bytes
            + len(message_type_bytes).to_bytes(
                1,
                "big",
            )
            + message_type_bytes
            + len(self.payload).to_bytes(
                4,
                "big",
            )
            + self.payload
        )

    @classmethod
    def decode(
        cls,
        data: bytes,
    ) -> "ApplicationMessage":
        position = 0

        if len(data) < 1:
            raise ValueError(
                "Invalid application message"
            )

        message_id_length = data[position]
        position += 1

        if (
            message_id_length <= 0
            or position + message_id_length > len(data)
        ):
            raise ValueError(
                "Invalid message ID"
            )

        message_id = UUID(
            data[
                position:
                position + message_id_length
            ].decode("ascii")
        )

        position += message_id_length

        if position >= len(data):
            raise ValueError(
                "Missing message type"
            )

        message_type_length = data[position]
        position += 1

        if (
            message_type_length <= 0
            or position + message_type_length > len(data)
        ):
            raise ValueError(
                "Invalid message type"
            )

        message_type = data[
            position:
            position + message_type_length
        ].decode("utf-8")

        position += message_type_length

        if position + 4 > len(data):
            raise ValueError(
                "Missing payload length"
            )

        payload_length = int.from_bytes(
            data[
                position:
                position + 4
            ],
            "big",
        )

        position += 4

        if (
            payload_length < 0
            or position + payload_length != len(data)
        ):
            raise ValueError(
                "Invalid payload length"
            )

        payload = data[
            position:
            position + payload_length
        ]

        return cls(
            message_type=message_type,
            payload=payload,
            message_id=message_id,
        )