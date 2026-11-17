from typing import Awaitable, Callable

from message_types import MessageType
from protocol import Frame
from dht_messages import FindNodeRequest
from dht_messages import FindNodeResponse
from dht_messages import StoreRequest
from dht_messages import StoreResponse
from dht_messages import FindValueRequest
from dht_messages import FindValueResponse
from routing_table import RoutingTable
from dht_storage import DHTStorage


Handler = Callable[[Frame], Awaitable[Frame]]


class Dispatcher:
    def __init__(
        self,
        routing_table: RoutingTable,
        storage: DHTStorage | None = None,
    ):
        self.routing_table = routing_table
        self.storage = (
            storage
            if storage is not None
            else DHTStorage()
        )

        self.handlers: dict[MessageType, Handler] = {
            MessageType.PING: self.handle_ping,
            MessageType.FIND_NODE_REQUEST: self.handle_find_node,
            MessageType.STORE_REQUEST: self.handle_store,
            MessageType.FIND_VALUE_REQUEST: self.handle_find_value,
        }

    async def dispatch(self, frame: Frame) -> Frame:
        try:
            message_type = MessageType(frame.message_type)

        except ValueError:
            return Frame(
                message_type=MessageType.ERROR,
                payload=b"Unknown message type",
                request_id=frame.request_id,
            )

        handler = self.handlers.get(message_type)

        if handler is None:
            return Frame(
                message_type=MessageType.ERROR,
                payload=b"Message type is not implemented",
                request_id=frame.request_id,
            )

        try:
            return await handler(frame)

        except Exception as error:
            return Frame(
                message_type=MessageType.ERROR,
                payload=str(error).encode("utf-8"),
                request_id=frame.request_id,
            )

    async def handle_ping(
        self,
        frame: Frame,
    ) -> Frame:
        return Frame(
            message_type=MessageType.PONG,
            payload=frame.payload,
            request_id=frame.request_id,
        )

    async def handle_find_node(
        self,
        frame: Frame,
    ) -> Frame:
        request = FindNodeRequest.decode(
            frame.payload
        )

        contacts = (
            self.routing_table.find_closest_nodes(
                target_node_id=request.target_node_id,
            )
        )

        response = FindNodeResponse(
            contacts=contacts
        )

        return Frame(
            message_type=MessageType.FIND_NODE_RESPONSE,
            payload=response.encode(),
            request_id=frame.request_id,
        )

    async def handle_store(
        self,
        frame: Frame,
    ) -> Frame:
        request = StoreRequest.decode(
            frame.payload
        )

        if not request.record.verify_signature():
            raise ValueError(
                "Invalid NodeRecord signature"
            )

        self.storage.store(
            request.record
        )

        response = StoreResponse(
            success=True
        )

        return Frame(
            message_type=MessageType.STORE_RESPONSE,
            payload=response.encode(),
            request_id=frame.request_id,
        )

    async def handle_find_value(
        self,
        frame: Frame,
    ) -> Frame:
        request = FindValueRequest.decode(
            frame.payload
        )

        record = self.storage.get(
            request.node_id
        )

        if record is not None:
            response = FindValueResponse(
                record=record,
                contacts=[],
            )

        else:
            contacts = (
                self.routing_table.find_closest_nodes(
                    target_node_id=request.node_id,
                )
            )

            response = FindValueResponse(
                record=None,
                contacts=contacts,
            )

        return Frame(
            message_type=MessageType.FIND_VALUE_RESPONSE,
            payload=response.encode(),
            request_id=frame.request_id,
        )