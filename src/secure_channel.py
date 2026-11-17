import os
from uuid import UUID
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecureChannel:
    """
    Симметричный защищённый канал:
    - Поддерживает раздельные направленные ключи и единый симметричный ключ.
    - Включает session_id в AAD при наличии сессии (защита от межсессионного replay).
    - Защищает от повторов внутри сессии через отслеживание sequence_number.
    - Уничтожает ключи после закрытия канала (Раздел 11.3 ТЗ).
    """

    NONCE_SIZE = 12
    KEY_SIZE = 32
    SEQUENCE_SIZE = 8

    def __init__(
        self,
        send_key: bytes,
        recv_key: bytes | None = None,
        session_id: UUID | None = None,
    ):
        if recv_key is None:
            recv_key = send_key

        if len(send_key) != self.KEY_SIZE or len(recv_key) != self.KEY_SIZE:
            raise ValueError("AES-256 key must contain exactly 32 bytes")

        self.session_id = session_id
        self._aes_send: AESGCM | None = AESGCM(send_key)
        self._aes_recv: AESGCM | None = AESGCM(recv_key)
        self._closed = False

        self._send_sequence = 0
        self._received_sequences: set[int] = set()

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Уничтожает сессионные AEAD-ключи после закрытия канала."""
        self._aes_send = None
        self._aes_recv = None
        self._received_sequences.clear()
        self._closed = True

    def encrypt(self, plaintext: bytes, associated_data: bytes | None = None) -> bytes:
        if self._closed or self._aes_send is None:
            raise RuntimeError("SecureChannel is closed; session keys destroyed")

        seq = self._send_sequence
        self._send_sequence += 1
        seq_bytes = seq.to_bytes(self.SEQUENCE_SIZE, byteorder="big")
        nonce = os.urandom(self.NONCE_SIZE)

        session_part = self.session_id.bytes if self.session_id is not None else b""
        aad = session_part + seq_bytes + (associated_data or b"")
        ciphertext = self._aes_send.encrypt(nonce, plaintext, aad)

        return seq_bytes + nonce + ciphertext

    def decrypt(self, encrypted: bytes, associated_data: bytes | None = None) -> bytes:
        if self._closed or self._aes_recv is None:
            raise RuntimeError("SecureChannel is closed; session keys destroyed")

        min_size = self.SEQUENCE_SIZE + self.NONCE_SIZE + 16
        if len(encrypted) < min_size:
            raise ValueError("Encrypted message is too short")

        seq_bytes = encrypted[:self.SEQUENCE_SIZE]
        seq = int.from_bytes(seq_bytes, byteorder="big")
        nonce = encrypted[self.SEQUENCE_SIZE : self.SEQUENCE_SIZE + self.NONCE_SIZE]
        ciphertext = encrypted[self.SEQUENCE_SIZE + self.NONCE_SIZE :]

        session_part = self.session_id.bytes if self.session_id is not None else b""
        aad = session_part + seq_bytes + (associated_data or b"")

        plaintext = self._aes_recv.decrypt(nonce, ciphertext, aad)

        if seq in self._received_sequences:
            raise ValueError("Replay attack detected")

        self._received_sequences.add(seq)
        return plaintext