from contact import Contact
from dht_messages import (
    FindValueRequest,
    FindValueResponse,
    NodeRecord,
)


def make_record() -> NodeRecord:
    return NodeRecord(
        node_id="a" * 64,
        identity_public_key="public-key",
        addresses=["127.0.0.1:9000"],
        sequence_number=1,
        issued_at=1000,
        expires_at=1300,
        signature="signature",
    )


def test_find_value_request_roundtrip():
    request = FindValueRequest(
        node_id="a" * 64
    )

    encoded = request.encode()

    decoded = FindValueRequest.decode(
        encoded
    )

    assert decoded == request


def test_find_value_request_rejects_invalid_node_id():
    request = FindValueRequest(
        node_id="invalid"
    )

    encoded = request.encode()

    try:
        FindValueRequest.decode(encoded)
        assert False
    except ValueError:
        pass


def test_find_value_response_with_record_roundtrip():
    record = make_record()

    response = FindValueResponse(
        record=record,
        contacts=[],
    )

    encoded = response.encode()

    decoded = FindValueResponse.decode(
        encoded
    )

    assert decoded.record == record
    assert decoded.contacts == []


def test_find_value_response_with_contacts_roundtrip():
    contacts = [
        Contact(
            node_id="a" * 64,
            host="127.0.0.1",
            port=9001,
        ),
        Contact(
            node_id="b" * 64,
            host="127.0.0.1",
            port=9002,
        ),
    ]

    response = FindValueResponse(
        record=None,
        contacts=contacts,
    )

    encoded = response.encode()

    decoded = FindValueResponse.decode(
        encoded
    )

    assert decoded.record is None
    assert decoded.contacts == contacts