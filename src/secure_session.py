import hashlib
import os
import struct
from dataclasses import dataclass
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from identity import Identity
from protocol import PROTOCOL_VERSION


@dataclass
class HandshakeHello:
    version: int
    node_id: str
    identity_public_key: bytes
    ephemeral_public_key: bytes
    nonce: bytes
    signature: bytes = b""

    def signing_data(self) -> bytes:
        return (
            bytes.fromhex(self.node_id)
            + self.identity_public_key
            + self.ephemeral_public_key
        )

    def encode(self) -> bytes:
        return (
            struct.pack("!B", self.version)
            + bytes.fromhex(self.node_id)
            + self.identity_public_key
            + self.ephemeral_public_key
            + self.nonce
        )

    @classmethod
    def decode(cls, data: bytes) -> "HandshakeHello":
        if len(data) != 1 + 32 + 32 + 32 + 16:
            raise ValueError("Invalid HandshakeHello length")
        return cls(
            version=data[0],
            node_id=data[1:33].hex(),
            identity_public_key=data[33:65],
            ephemeral_public_key=data[65:97],
            nonce=data[97:113],
        )


SessionHello = HandshakeHello


@dataclass
class HandshakeAuth:
    version: int
    session_id: UUID
    node_id: str
    identity_public_key: bytes
    ephemeral_public_key: bytes
    nonce: bytes
    signature: bytes

    def encode(self) -> bytes:
        return (
            struct.pack("!B", self.version)
            + self.session_id.bytes
            + bytes.fromhex(self.node_id)
            + self.identity_public_key
            + self.ephemeral_public_key
            + self.nonce
            + self.signature
        )

    @classmethod
    def decode(cls, data: bytes) -> "HandshakeAuth":
        if len(data) != 1 + 16 + 32 + 32 + 32 + 16 + 64:
            raise ValueError("Invalid HandshakeAuth length")
        return cls(
            version=data[0],
            session_id=UUID(bytes=data[1:17]),
            node_id=data[17:49].hex(),
            identity_public_key=data[49:81],
            ephemeral_public_key=data[81:113],
            nonce=data[113:129],
            signature=data[129:193],
        )


@dataclass
class HandshakeFinished:
    session_id: UUID
    signature: bytes

    def encode(self) -> bytes:
        return self.session_id.bytes + self.signature

    @classmethod
    def decode(cls, data: bytes) -> "HandshakeFinished":
        if len(data) != 16 + 64:
            raise ValueError("Invalid HandshakeFinished length")
        return cls(
            session_id=UUID(bytes=data[:16]),
            signature=data[16:],
        )


class SecureSession:
    """
    Аутентифицированное установление сессии (Раздел 11.3 ТЗ).
    Поддерживает:
    - Полный 4-шаговый транскрипт с разделением направлений ключей.
    - Быстрый симметричный accept_hello для туннельных сценариев.
    - Уничтожение сессионных и эфемерных ключей после закрытия (close / destroy_keys).
    """

    def __init__(self, identity: Identity, is_initiator: bool = True):
        self.identity = identity
        self.is_initiator = is_initiator
        self.session_id: UUID | None = None

        self._ephemeral_private_key: x25519.X25519PrivateKey | None = (
            x25519.X25519PrivateKey.generate()
        )
        self._local_nonce = os.urandom(16)

        self._remote_node_id: str | None = None
        self._remote_identity_pk: bytes | None = None
        self._remote_ephemeral_pk: bytes | None = None
        self._remote_nonce: bytes | None = None

        self._shared_secret: bytes | None = None
        self._session_key: bytes | None = None
        self.send_key: bytes | None = None
        self.recv_key: bytes | None = None
        self._closed: bool = False

    @property
    def shared_secret(self) -> bytes | None:
        return self._shared_secret

    @property
    def session_key(self) -> bytes | None:
        return self._session_key if self._session_key is not None else self.send_key

    @property
    def established(self) -> bool:
        if self._closed:
            return False
        return self.session_key is not None or (
            self.send_key is not None and self.recv_key is not None
        )

    def close(self) -> None:
        """Уничтожает эфемерные и сессионные ключи после закрытия сессии (Раздел 11.3 ТЗ)."""
        self._ephemeral_private_key = None
        self._shared_secret = None
        self._session_key = None
        self.send_key = None
        self.recv_key = None
        self._closed = True

    destroy_keys = close

    def create_hello(self) -> HandshakeHello:
        if self._ephemeral_private_key is None:
            raise RuntimeError("Session is closed")

        eph_bytes = self._ephemeral_private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        id_bytes = self.identity.public_key.public_bytes_raw()
        sign_data = bytes.fromhex(self.identity.node_id) + id_bytes + eph_bytes
        sig = self.identity.sign(sign_data)

        return HandshakeHello(
            version=PROTOCOL_VERSION,
            node_id=self.identity.node_id,
            identity_public_key=id_bytes,
            ephemeral_public_key=eph_bytes,
            nonce=self._local_nonce,
            signature=sig,
        )

    @staticmethod
    def verify_hello(hello: HandshakeHello) -> bool:
        calc = hashlib.sha256(hello.identity_public_key).hexdigest()
        if calc != hello.node_id:
            return False
        if hello.signature:
            sign_data = (
                bytes.fromhex(hello.node_id)
                + hello.identity_public_key
                + hello.ephemeral_public_key
            )
            return Identity.verify(hello.identity_public_key, sign_data, hello.signature)
        return True

    def accept_hello(self, hello: HandshakeHello) -> None:
        if self._ephemeral_private_key is None:
            raise RuntimeError("Session is closed")
        if not self.verify_hello(hello):
            raise ValueError("Invalid session hello")

        self._remote_node_id = hello.node_id
        self._remote_identity_pk = hello.identity_public_key
        self._remote_ephemeral_pk = hello.ephemeral_public_key
        self._remote_nonce = hello.nonce

        remote_eph = x25519.X25519PublicKey.from_public_bytes(hello.ephemeral_public_key)
        self._shared_secret = self._ephemeral_private_key.exchange(remote_eph)

        node_ids = sorted([self.identity.node_id, hello.node_id])
        salt = bytes.fromhex(node_ids[0]) + bytes.fromhex(node_ids[1])
        info = b"overlay-network-secure-session-v1"
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=info,
        ).derive(self._shared_secret)

        sid_bytes = hashlib.sha256(salt + self._shared_secret).digest()[:16]
        self.session_id = UUID(bytes=sid_bytes)

        self._session_key = key
        self.send_key = key
        self.recv_key = key

    def _build_transcript(self, signing_role: bytes) -> bytes:
        if self._ephemeral_private_key is None:
            raise RuntimeError("Session is closed")

        if self.is_initiator:
            init_nid = bytes.fromhex(self.identity.node_id)
            resp_nid = bytes.fromhex(self._remote_node_id)
            init_id_pk = self.identity.public_key.public_bytes_raw()
            resp_id_pk = self._remote_identity_pk
            init_eph_pk = self._ephemeral_private_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            resp_eph_pk = self._remote_ephemeral_pk
            init_nonce = self._local_nonce
            resp_nonce = self._remote_nonce
        else:
            init_nid = bytes.fromhex(self._remote_node_id)
            resp_nid = bytes.fromhex(self.identity.node_id)
            init_id_pk = self._remote_identity_pk
            resp_id_pk = self.identity.public_key.public_bytes_raw()
            init_eph_pk = self._remote_ephemeral_pk
            resp_eph_pk = self._ephemeral_private_key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            init_nonce = self._remote_nonce
            resp_nonce = self._local_nonce

        return (
            struct.pack("!B", PROTOCOL_VERSION)
            + signing_role
            + self.session_id.bytes
            + init_nid
            + resp_nid
            + init_id_pk
            + resp_id_pk
            + init_eph_pk
            + resp_eph_pk
            + init_nonce
            + resp_nonce
        )

    def handle_hello(self, hello: HandshakeHello) -> HandshakeAuth:
        if self.is_initiator:
            raise RuntimeError("Инициатор не обрабатывает Hello")

        calc_id = hashlib.sha256(hello.identity_public_key).hexdigest()
        if calc_id != hello.node_id:
            raise ValueError("NodeID не соответствует открытому ключу инициатора")

        self._remote_node_id = hello.node_id
        self._remote_identity_pk = hello.identity_public_key
        self._remote_ephemeral_pk = hello.ephemeral_public_key
        self._remote_nonce = hello.nonce
        self.session_id = uuid4()

        remote_eph = x25519.X25519PublicKey.from_public_bytes(hello.ephemeral_public_key)
        self._shared_secret = self._ephemeral_private_key.exchange(remote_eph)
        self._derive_directional_keys()

        transcript = self._build_transcript(signing_role=b"RESPONDER")
        sig = self.identity.sign(transcript)

        eph_bytes = self._ephemeral_private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return HandshakeAuth(
            version=PROTOCOL_VERSION,
            session_id=self.session_id,
            node_id=self.identity.node_id,
            identity_public_key=self.identity.public_key.public_bytes_raw(),
            ephemeral_public_key=eph_bytes,
            nonce=self._local_nonce,
            signature=sig,
        )

    def handle_auth(self, auth: HandshakeAuth) -> HandshakeFinished:
        if not self.is_initiator:
            raise RuntimeError("Только инициатор обрабатывает Auth")

        calc_id = hashlib.sha256(auth.identity_public_key).hexdigest()
        if calc_id != auth.node_id:
            raise ValueError("NodeID не соответствует открытому ключу ответчика")

        self.session_id = auth.session_id
        self._remote_node_id = auth.node_id
        self._remote_identity_pk = auth.identity_public_key
        self._remote_ephemeral_pk = auth.ephemeral_public_key
        self._remote_nonce = auth.nonce

        transcript_resp = self._build_transcript(signing_role=b"RESPONDER")
        if not Identity.verify(auth.identity_public_key, transcript_resp, auth.signature):
            raise ValueError("Недействительная подпись рукопожатия ответчика")

        remote_eph = x25519.X25519PublicKey.from_public_bytes(auth.ephemeral_public_key)
        self._shared_secret = self._ephemeral_private_key.exchange(remote_eph)
        self._derive_directional_keys()

        transcript_init = self._build_transcript(signing_role=b"INITIATOR")
        init_sig = self.identity.sign(transcript_init)
        return HandshakeFinished(session_id=self.session_id, signature=init_sig)

    def handle_finished(self, fin: HandshakeFinished) -> None:
        if self.is_initiator:
            raise RuntimeError("Инициатор не обрабатывает Finished")

        if fin.session_id != self.session_id:
            raise ValueError("Несоответствие session_id")

        transcript_init = self._build_transcript(signing_role=b"INITIATOR")
        if not Identity.verify(self._remote_identity_pk, transcript_init, fin.signature):
            raise ValueError("Недействительная подпись подтверждения инициатора")

    def _derive_directional_keys(self) -> None:
        if self.is_initiator:
            init_nid = self.identity.node_id
            resp_nid = self._remote_node_id
        else:
            init_nid = self._remote_node_id
            resp_nid = self.identity.node_id

        salt = bytes.fromhex(init_nid) + bytes.fromhex(resp_nid)
        hkdf_base = HKDF(
            algorithm=hashes.SHA256(),
            length=64,
            salt=salt,
            info=b"overlay-v1-directional-keys",
        ).derive(self._shared_secret)

        k_init_to_resp = hkdf_base[:32]
        k_resp_to_init = hkdf_base[32:]

        if self.is_initiator:
            self.send_key = k_init_to_resp
            self.recv_key = k_resp_to_init
        else:
            self.send_key = k_resp_to_init
            self.recv_key = k_init_to_resp