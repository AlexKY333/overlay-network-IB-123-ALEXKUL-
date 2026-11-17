import sys
from pathlib import Path


sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from identity import Identity


def test_identity_signature():
    identity = Identity(
        state_dir="test_identity_signature_state"
    )

    data = b"overlay network test message"

    signature = identity.sign(
        data
    )

    public_key = (
        identity.public_key.public_bytes_raw()
    )

    assert Identity.verify(
        public_key,
        data,
        signature,
    ) is True


def test_identity_signature_rejects_modified_data():
    identity = Identity(
        state_dir="test_identity_signature_state_2"
    )

    data = b"original message"

    signature = identity.sign(
        data
    )

    public_key = (
        identity.public_key.public_bytes_raw()
    )

    assert Identity.verify(
        public_key,
        b"modified message",
        signature,
    ) is False


def test_identity_signature_rejects_wrong_public_key():
    identity_a = Identity(
        state_dir="test_identity_signature_state_3_a"
    )

    identity_b = Identity(
        state_dir="test_identity_signature_state_3_b"
    )

    data = b"overlay network message"

    signature = identity_a.sign(
        data
    )

    public_key_b = (
        identity_b.public_key.public_bytes_raw()
    )

    assert Identity.verify(
        public_key_b,
        data,
        signature,
    ) is False

if __name__ == "__main__":
    test_identity_signature()