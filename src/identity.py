from pathlib import Path
import hashlib

from cryptography.hazmat.primitives.asymmetric import ed25519


class Identity:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.key_file = self.state_dir / "identity.key"

        self.state_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        if self.key_file.exists():
            self._load_key()
        else:
            self._generate_key()
            self._save_key()

        self.public_key = self.private_key.public_key()
        self.node_id = self._calculate_node_id()

    def _generate_key(self):
        self.private_key = (
            ed25519.Ed25519PrivateKey.generate()
        )

    def _save_key(self):
        private_bytes = self.private_key.private_bytes_raw()

        self.key_file.write_bytes(
            private_bytes
        )

    def _load_key(self):
        private_bytes = self.key_file.read_bytes()

        self.private_key = (
            ed25519.Ed25519PrivateKey.from_private_bytes(
                private_bytes
            )
        )

    def _calculate_node_id(self) -> str:
        public_bytes = self.public_key.public_bytes_raw()

        return hashlib.sha256(
            public_bytes
        ).hexdigest()

    def verify_node_id(
        self,
        public_key_bytes: bytes,
        claimed_node_id: str,
    ) -> bool:
        calculated_node_id = hashlib.sha256(
            public_key_bytes
        ).hexdigest()

        return calculated_node_id == claimed_node_id

    def sign(
        self,
        data: bytes,
    ) -> bytes:
        return self.private_key.sign(
            data
        )

    @staticmethod
    def verify(
        public_key_bytes: bytes,
        data: bytes,
        signature: bytes,
    ) -> bool:
        try:
            public_key = (
                ed25519.Ed25519PublicKey.from_public_bytes(
                    public_key_bytes
                )
            )

            public_key.verify(
                signature,
                data,
            )

            return True

        except Exception:
            return False