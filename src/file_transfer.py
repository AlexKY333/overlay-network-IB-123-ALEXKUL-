import hashlib
import math
from dataclasses import dataclass
from uuid import UUID, uuid4
from config import FILE_CHUNK_SIZE

@dataclass
class FileChunk:
    transfer_id: UUID
    filename: str
    file_size: int
    chunk_index: int
    total_chunks: int
    file_hash: str
    payload: bytes

    MESSAGE_TYPE = "FILE_CHUNK"

    def __post_init__(self):
        if self.file_size < 0:
            raise ValueError(
                "file_size cannot be negative"
            )

        if self.chunk_index < 0:
            raise ValueError(
                "chunk_index cannot be negative"
            )

        if self.total_chunks <= 0:
            raise ValueError(
                "total_chunks must be positive"
            )

        if self.chunk_index >= self.total_chunks:
            raise ValueError(
                "chunk_index is outside transfer"
            )

        if len(self.file_hash) != 64:
            raise ValueError(
                "file_hash must be SHA-256 hex"
            )

        try:
            int(self.file_hash, 16)
        except ValueError:
            raise ValueError(
                "file_hash must contain hexadecimal characters"
            )

        if not isinstance(self.payload, bytes):
            raise TypeError(
                "payload must be bytes"
            )

    def to_application_message(self):
        from application_message import ApplicationMessage

        metadata = (
            str(self.transfer_id)
            + "|"
            + self.filename
            + "|"
            + str(self.file_size)
            + "|"
            + str(self.chunk_index)
            + "|"
            + str(self.total_chunks)
            + "|"
            + self.file_hash
        ).encode("utf-8")

        return ApplicationMessage(
            message_type=self.MESSAGE_TYPE,
            payload=(
                metadata
                + b"\n\n"
                + self.payload
            ),
        )

    @classmethod
    def from_application_message(
        cls,
        message,
    ) -> "FileChunk":
        if message.message_type != cls.MESSAGE_TYPE:
            raise ValueError(
                "Expected FILE_CHUNK message"
            )

        separator = b"\n\n"

        if separator not in message.payload:
            raise ValueError(
                "Invalid file chunk format"
            )

        metadata, payload = (
            message.payload.split(
                separator,
                1,
            )
        )

        fields = metadata.decode(
            "utf-8"
        ).split("|")

        if len(fields) != 6:
            raise ValueError(
                "Invalid file chunk metadata"
            )

        (
            transfer_id,
            filename,
            file_size,
            chunk_index,
            total_chunks,
            file_hash,
        ) = fields

        return cls(
            transfer_id=UUID(transfer_id),
            filename=filename,
            file_size=int(file_size),
            chunk_index=int(chunk_index),
            total_chunks=int(total_chunks),
            file_hash=file_hash,
            payload=payload,
        )


class FileTransfer:
    DEFAULT_CHUNK_SIZE = FILE_CHUNK_SIZE

    def __init__(
        self,
        filename: str,
        data: bytes,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        transfer_id: UUID | None = None,
    ):
        if not filename:
            raise ValueError(
                "filename cannot be empty"
            )

        if not isinstance(data, bytes):
            raise TypeError(
                "data must be bytes"
            )

        if chunk_size <= 0:
            raise ValueError(
                "chunk_size must be positive"
            )

        self.filename = filename
        self.data = data
        self.chunk_size = chunk_size

        self.transfer_id = (
            transfer_id
            if transfer_id is not None
            else uuid4()
        )

        self.file_hash = hashlib.sha256(
            data
        ).hexdigest()

        self.total_chunks = max(
            1,
            math.ceil(
                len(data) / chunk_size
            ),
        )

    def chunks(self) -> list[FileChunk]:
        result = []

        for index in range(
            self.total_chunks
        ):
            start = (
                index
                * self.chunk_size
            )

            end = min(
                start + self.chunk_size,
                len(self.data),
            )

            payload = self.data[
                start:end
            ]

            result.append(
                FileChunk(
                    transfer_id=self.transfer_id,
                    filename=self.filename,
                    file_size=len(self.data),
                    chunk_index=index,
                    total_chunks=self.total_chunks,
                    file_hash=self.file_hash,
                    payload=payload,
                )
            )

        return result

    def encrypt_chunks(
        self,
        encrypted_tunnel,
    ) -> list[bytes]:
        """
        Преобразует все чанки файла
        в зашифрованные сообщения.
        """

        encrypted_messages = []

        for chunk in self.chunks():
            message = (
                chunk.to_application_message()
            )

            encrypted = (
                encrypted_tunnel
                .encrypt_application_message(
                    message
                )
            )

            encrypted_messages.append(
                encrypted
            )

        return encrypted_messages


class FileTransferReceiver:
    def __init__(self):
        self._transfers = {}

    def receive_chunk(
        self,
        chunk: FileChunk,
    ) -> bytes | None:
        transfer_id = chunk.transfer_id

        if transfer_id not in self._transfers:
            self._transfers[
                transfer_id
            ] = {
                "filename": chunk.filename,
                "file_size": chunk.file_size,
                "total_chunks": chunk.total_chunks,
                "file_hash": chunk.file_hash,
                "chunks": {},
            }

        transfer = self._transfers[
            transfer_id
        ]

        if (
            transfer["filename"]
            != chunk.filename
        ):
            raise ValueError(
                "Filename mismatch"
            )

        if (
            transfer["file_size"]
            != chunk.file_size
        ):
            raise ValueError(
                "File size mismatch"
            )

        if (
            transfer["total_chunks"]
            != chunk.total_chunks
        ):
            raise ValueError(
                "Total chunks mismatch"
            )

        if (
            transfer["file_hash"]
            != chunk.file_hash
        ):
            raise ValueError(
                "File hash mismatch"
            )

        transfer["chunks"][
            chunk.chunk_index
        ] = chunk.payload

        if len(
            transfer["chunks"]
        ) != transfer["total_chunks"]:
            return None

        data = b"".join(
            transfer["chunks"][index]
            for index in range(
                transfer["total_chunks"]
            )
        )

        if len(data) != transfer["file_size"]:
            raise ValueError(
                "Received file size does not match"
            )

        calculated_hash = (
            hashlib.sha256(data)
            .hexdigest()
        )

        if (
            calculated_hash
            != transfer["file_hash"]
        ):
            raise ValueError(
                "File integrity check failed"
            )

        del self._transfers[
            transfer_id
        ]

        return data

    def receive_encrypted_message(
        self,
        encrypted_tunnel,
        encrypted_data: bytes,
    ) -> bytes | None:
        """
        Расшифровывает FILE_CHUNK
        и передаёт его сборщику файла.
        """

        message = (
            encrypted_tunnel
            .decrypt_application_message(
                encrypted_data
            )
        )

        chunk = (
            FileChunk
            .from_application_message(
                message
            )
        )

        return self.receive_chunk(
            chunk
        )

class FileTransferResume:
    """
    Управляет возобновлением передачи файла.

    Хранит номера чанков, которые уже получили
    подтверждение (ACK).

    После отказа маршрута можно создать новый
    маршрут и продолжить передачу только
    неподтверждённых чанков.
    """

    def __init__(
        self,
        transfer: FileTransfer,
    ):
        if not isinstance(
            transfer,
            FileTransfer,
        ):
            raise TypeError(
                "transfer must be FileTransfer"
            )

        self.transfer = transfer

        self._chunks = {
            chunk.chunk_index: chunk
            for chunk in transfer.chunks()
        }

        self._acknowledged: set[int] = set()

    @property
    def total_chunks(self) -> int:
        return self.transfer.total_chunks

    @property
    def acknowledged_chunks(self) -> set[int]:
        return set(
            self._acknowledged
        )

    @property
    def acknowledged_count(self) -> int:
        return len(
            self._acknowledged
        )

    @property
    def is_complete(self) -> bool:
        return (
            self.acknowledged_count
            == self.total_chunks
        )

    def acknowledge(
        self,
        chunk_index: int,
    ) -> None:
        if chunk_index not in self._chunks:
            raise ValueError(
                "Unknown chunk index"
            )

        self._acknowledged.add(
            chunk_index
        )

    def is_acknowledged(
        self,
        chunk_index: int,
    ) -> bool:
        return (
            chunk_index
            in self._acknowledged
        )

    def pending_chunk_indices(
        self,
    ) -> list[int]:
        return [
            index
            for index in range(
                self.total_chunks
            )
            if index
            not in self._acknowledged
        ]

    def pending_chunks(
        self,
    ) -> list[FileChunk]:
        return [
            self._chunks[index]
            for index in self.pending_chunk_indices()
        ]

    def next_pending_chunk(
        self,
    ) -> FileChunk | None:
        for index in range(
            self.total_chunks
        ):
            if index not in self._acknowledged:
                return self._chunks[index]

        return None

    def last_acknowledged_chunk(
        self,
    ) -> int | None:
        if not self._acknowledged:
            return None

        return max(
            self._acknowledged
        )