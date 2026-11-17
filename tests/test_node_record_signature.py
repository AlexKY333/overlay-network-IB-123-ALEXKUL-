import sys
from pathlib import Path

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent / "src"
    )
)

from identity import Identity
from dht_messages import NodeRecord


def create_identity(tmp_path, name):
    return Identity(
        tmp_path / name
    )


def test_node_record_signature_valid(tmp_path):
    identity = create_identity(
        tmp_path,
        "node_a"
    )

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=1000,
        expires_at=1200,
    )

    assert record.node_id == identity.node_id
    assert record.identity_public_key
    assert record.signature
    assert record.verify_signature()


def test_node_record_signature_rejects_modified_data(tmp_path):
    identity = create_identity(
        tmp_path,
        "node_a"
    )

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=1000,
        expires_at=1200,
    )

    assert record.verify_signature()

    record.sequence_number = 2

    assert not record.verify_signature()


def test_node_record_signature_rejects_wrong_node_id(tmp_path):
    identity = create_identity(
        tmp_path,
        "node_a"
    )

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=1000,
        expires_at=1200,
    )

    record.node_id = "0" * 64

    assert not record.verify_signature()


def test_node_record_signature_survives_encode_decode(tmp_path):
    identity = create_identity(
        tmp_path,
        "node_a"
    )

    record = NodeRecord.create_signed(
        identity=identity,
        addresses=[
            "127.0.0.1:9000",
            "127.0.0.1:9001",
        ],
        sequence_number=5,
        issued_at=1000,
        expires_at=1200,
    )

    encoded = record.encode()

    decoded = NodeRecord.decode(encoded)

    assert decoded.node_id == record.node_id
    assert decoded.identity_public_key == record.identity_public_key
    assert decoded.addresses == record.addresses
    assert decoded.sequence_number == record.sequence_number
    assert decoded.issued_at == record.issued_at
    assert decoded.expires_at == record.expires_at
    assert decoded.signature == record.signature

    assert decoded.verify_signature()