from dataclasses import dataclass
import base64
import hashlib

from contact import Contact
from identity import Identity


@dataclass
class FindNodeRequest:
    target_node_id: str

    def encode(self) -> bytes:
        return self.target_node_id.encode("ascii")

    @classmethod
    def decode(cls, data: bytes) -> "FindNodeRequest":
        target_node_id = data.decode("ascii")

        if len(target_node_id) != 64:
            raise ValueError("Invalid target NodeID length")

        int(target_node_id, 16)

        return cls(
            target_node_id=target_node_id
        )


@dataclass
class FindNodeResponse:
    contacts: list[Contact]

    def encode(self) -> bytes:
        lines = []

        for contact in self.contacts:
            lines.append(
                f"{contact.node_id}|{contact.host}|{contact.port}"
            )

        return "\n".join(lines).encode("ascii")

    @classmethod
    def decode(cls, data: bytes) -> "FindNodeResponse":
        if not data:
            return cls(contacts=[])

        contacts = []

        for line in data.decode("ascii").split("\n"):
            parts = line.split("|")

            if len(parts) != 3:
                raise ValueError("Invalid contact format")

            node_id, host, port_text = parts

            if len(node_id) != 64:
                raise ValueError("Invalid NodeID length")

            int(node_id, 16)

            try:
                port = int(port_text)
            except ValueError:
                raise ValueError("Invalid port")

            contacts.append(
                Contact(
                    node_id=node_id,
                    host=host,
                    port=port
                )
            )

        return cls(
            contacts=contacts
        )


@dataclass
class NodeRecord:
    node_id: str
    identity_public_key: str
    addresses: list[str]
    sequence_number: int
    issued_at: int
    expires_at: int
    signature: str
    alias: str = ""

    # ============================================================
    # ALIAS
    # ============================================================

    @staticmethod
    def normalize_alias(alias: str) -> str:
        """
        Нормализует alias перед вычислением ключа.

        Например:

            " Alice " -> "alice"
            "ALICE"   -> "alice"
        """

        if not isinstance(alias, str):
            raise TypeError(
                "alias must be a string"
            )

        normalized = alias.strip().casefold()

        if not normalized:
            raise ValueError(
                "alias cannot be empty"
            )

        return normalized

    @classmethod
    def alias_key(cls, alias: str) -> str:
        """
        Возвращает DHT-ключ для alias.

        Формула:

            SHA-256("alias:" || normalize(alias))
        """

        normalized = cls.normalize_alias(
            alias
        )

        data = (
            "alias:" + normalized
        ).encode("utf-8")

        return hashlib.sha256(
            data
        ).hexdigest()

    # ============================================================
    # SIGNATURE
    # ============================================================

    def canonical_bytes(self) -> bytes:
        """
        Возвращает точные байты, которые подписываются.

        Alias также входит в подписываемые данные,
        поэтому его нельзя изменить после подписи.
        """

        lines = [
            self.node_id,
            self.identity_public_key,
            ",".join(self.addresses),
            str(self.sequence_number),
            str(self.issued_at),
            str(self.expires_at),
            self.alias,
        ]

        return "\n".join(lines).encode("utf-8")

    def sign(self, identity: Identity) -> None:
        """
        Подписывает NodeRecord указанным Identity.
        """

        if self.node_id != identity.node_id:
            raise ValueError(
                "NodeRecord node_id does not match identity"
            )

        if self.alias:
            self.alias = self.normalize_alias(
                self.alias
            )

        public_key_bytes = (
            identity.public_key.public_bytes_raw()
        )

        self.identity_public_key = (
            base64.b64encode(
                public_key_bytes
            ).decode("ascii")
        )

        signature_bytes = identity.sign(
            self.canonical_bytes()
        )

        self.signature = (
            base64.b64encode(
                signature_bytes
            ).decode("ascii")
        )

    def verify_signature(self) -> bool:
        """
        Проверяет:

        1. NodeID соответствует public key;
        2. alias имеет корректный формат;
        3. Ed25519-подпись корректна.
        """

        try:
            public_key_bytes = (
                base64.b64decode(
                    self.identity_public_key,
                    validate=True,
                )
            )

            signature_bytes = (
                base64.b64decode(
                    self.signature,
                    validate=True,
                )
            )

        except Exception:
            return False

        calculated_node_id = (
            hashlib.sha256(
                public_key_bytes
            ).hexdigest()
        )

        if calculated_node_id != self.node_id:
            return False

        if self.alias:
            try:
                normalized_alias = (
                    self.normalize_alias(
                        self.alias
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                return False

            if normalized_alias != self.alias:
                return False

        return Identity.verify(
            public_key_bytes=public_key_bytes,
            data=self.canonical_bytes(),
            signature=signature_bytes,
        )

    @classmethod
    def create_signed(
        cls,
        identity: Identity,
        addresses: list[str],
        sequence_number: int,
        issued_at: int,
        expires_at: int,
        alias: str = "",
    ) -> "NodeRecord":
        """
        Создаёт и подписывает NodeRecord.

        alias оставлен необязательным для обратной совместимости
        со старым кодом проекта.
        """

        normalized_alias = ""

        if alias:
            normalized_alias = cls.normalize_alias(
                alias
            )

        record = cls(
            node_id=identity.node_id,
            identity_public_key="",
            addresses=addresses,
            sequence_number=sequence_number,
            issued_at=issued_at,
            expires_at=expires_at,
            signature="",
            alias=normalized_alias,
        )

        record.sign(identity)

        return record

    # ============================================================
    # SERIALIZATION
    # ============================================================

    def encode(self) -> bytes:
        """
        Новый формат содержит alias:

        node_id
        identity_public_key
        addresses
        sequence_number
        issued_at
        expires_at
        alias
        signature
        """

        lines = [
            self.node_id,
            self.identity_public_key,
            ",".join(self.addresses),
            str(self.sequence_number),
            str(self.issued_at),
            str(self.expires_at),
            self.alias,
            self.signature,
        ]

        return "\n".join(
            lines
        ).encode("utf-8")

    @classmethod
    def decode(
        cls,
        data: bytes,
    ) -> "NodeRecord":
        """
        Поддерживает:

        старый формат — 7 строк;
        новый формат — 8 строк с alias.
        """

        lines = (
            data.decode("utf-8")
            .split("\n")
        )

        if len(lines) == 7:
            # Старый формат без alias.
            (
                node_id,
                identity_public_key,
                addresses_text,
                sequence_number_text,
                issued_at_text,
                expires_at_text,
                signature,
            ) = lines

            alias = ""

        elif len(lines) == 8:
            # Новый формат с alias.
            (
                node_id,
                identity_public_key,
                addresses_text,
                sequence_number_text,
                issued_at_text,
                expires_at_text,
                alias,
                signature,
            ) = lines

        else:
            raise ValueError(
                "Invalid NodeRecord format"
            )

        if len(node_id) != 64:
            raise ValueError(
                "Invalid NodeID length"
            )

        int(
            node_id,
            16,
        )

        addresses = []

        if addresses_text:
            addresses = (
                addresses_text.split(",")
            )

        try:
            sequence_number = int(
                sequence_number_text
            )

            issued_at = int(
                issued_at_text
            )

            expires_at = int(
                expires_at_text
            )

        except ValueError:
            raise ValueError(
                "Invalid NodeRecord numeric field"
            )

        if alias:
            alias = cls.normalize_alias(
                alias
            )

        return cls(
            node_id=node_id,
            identity_public_key=identity_public_key,
            addresses=addresses,
            sequence_number=sequence_number,
            issued_at=issued_at,
            expires_at=expires_at,
            signature=signature,
            alias=alias,
        )


@dataclass
class StoreRequest:
    record: NodeRecord

    def encode(self) -> bytes:
        return self.record.encode()

    @classmethod
    def decode(cls, data: bytes) -> "StoreRequest":
        return cls(
            record=NodeRecord.decode(data)
        )


@dataclass
class StoreResponse:
    success: bool

    def encode(self) -> bytes:
        return b"OK" if self.success else b"ERROR"

    @classmethod
    def decode(cls, data: bytes) -> "StoreResponse":
        if data == b"OK":
            return cls(success=True)

        if data == b"ERROR":
            return cls(success=False)

        raise ValueError("Invalid StoreResponse")


@dataclass
class FindValueRequest:
    node_id: str

    def encode(self) -> bytes:
        return self.node_id.encode("ascii")

    @classmethod
    def decode(cls, data: bytes) -> "FindValueRequest":
        node_id = data.decode("ascii")

        if len(node_id) != 64:
            raise ValueError("Invalid NodeID length")

        int(node_id, 16)

        return cls(
            node_id=node_id
        )


@dataclass
class FindValueResponse:
    record: NodeRecord | None
    contacts: list[Contact]

    def encode(self) -> bytes:
        if self.record is not None:
            return b"VALUE\n" + self.record.encode()

        lines = ["NODES"]

        for contact in self.contacts:
            lines.append(
                f"{contact.node_id}|{contact.host}|{contact.port}"
            )

        return "\n".join(lines).encode("utf-8")

    @classmethod
    def decode(cls, data: bytes) -> "FindValueResponse":
        if data.startswith(b"VALUE\n"):
            record = NodeRecord.decode(
                data[len(b"VALUE\n"):]
            )

            return cls(
                record=record,
                contacts=[],
            )

        text = data.decode("utf-8")

        lines = text.split("\n")

        if not lines or lines[0] != "NODES":
            raise ValueError("Invalid FindValueResponse")

        contacts = []

        for line in lines[1:]:
            if not line:
                continue

            parts = line.split("|")

            if len(parts) != 3:
                raise ValueError("Invalid contact format")

            node_id, host, port_text = parts

            if len(node_id) != 64:
                raise ValueError("Invalid NodeID length")

            int(node_id, 16)

            try:
                port = int(port_text)
            except ValueError:
                raise ValueError("Invalid port")

            contacts.append(
                Contact(
                    node_id=node_id,
                    host=host,
                    port=port,
                )
            )

        return cls(
            record=None,
            contacts=contacts,
        )